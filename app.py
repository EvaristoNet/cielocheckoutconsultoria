from flask import Flask, render_template, request, redirect, url_for, flash
import os
from datetime import datetime
import uuid

from cieloApi3 import *

from config import (
    CIELO_MERCHANT_ID,
    CIELO_MERCHANT_KEY,
    MONTHLY_INTEREST_RATE,
    CIELO_CAPTURE_IMMEDIATELY,
    CIELO_ENABLE_3DS,
    CIELO_CAPTURE_IMMEDIATELY_DONATION,
)
from utils import calc_installment_amount, BRL_to_cents


app = Flask(__name__)
app.secret_key = "change-this-in-production"


# Catálogo de planos (valores informados pelo usuário)
PLANS = [
    {"id": "30d", "label": "Conclusão em 30 dias", "months": 1, "price_brl": 1590.00},
    {"id": "3m", "label": "Conclusão em 3 meses", "months": 3, "price_brl": 1260.00},
    {"id": "6m", "label": "Conclusão em 6 meses", "months": 6, "price_brl": 999.99},
    {"id": "9m", "label": "Conclusão em 9 meses", "months": 9, "price_brl": 799.99},
    {"id": "12m", "label": "Conclusão em 12 meses", "months": 12, "price_brl": 599.99},
]


# Marcas de cartão suportadas pelo SDK
CARD_BRANDS = [
    "Visa",
    "Master",
    "Amex",
    "Elo",
    "Hipercard",
    "Diners",
    "Discover",
]

# Mapa de status Cielo (Ecommerce API)
STATUS_MAP = {
    0: "Não finalizado",
    1: "Autorizado",
    2: "Capturado",
    3: "Negado",
    10: "Cancelado",
    11: "Estornado",
    12: "Pendente",
    13: "Abortado",
    20: "Agendado",
}

def _status_text(code):
    return STATUS_MAP.get(code, f"Desconhecido ({code})")

# Mensagens comuns de ReturnCode da adquirente
RETURN_CODE_MAP = {
    "00": "Transação aprovada (autorizada).",
    "0": "Transação aprovada (autorizada).",
    "4": "Transação não autorizada pelo emissor.",
    "5": "Transação não autorizada. Verifique com o banco emissor.",
    "57": "Cartão não permite esse tipo de transação.",
    "82": "Cartão inválido ou não reconhecido.",
    "83": "CVV inválido.",
    "91": "Emissor indisponível. Tente novamente.",
}

def _return_code_text(code):
    try:
        c = str(code) if code is not None else ""
        return RETURN_CODE_MAP.get(c, f"Código {c} — consulte a adquirente para detalhes.")
    except Exception:
        return "Código não informado — consulte a adquirente."


def _parse_expiration(exp: str):
    """Valida e normaliza validade no formato MM/AAAA, retorna (mm, yyyy).
    Levanta ValueError se inválido.
    """
    if not exp or "/" not in exp:
        raise ValueError("Validade inválida. Use MM/AAAA.")
    mm_str, yy_str = exp.split("/", 1)
    mm = int(mm_str)
    yyyy = int(yy_str)
    if mm < 1 or mm > 12:
        raise ValueError("Mês inválido na validade.")
    current_year = datetime.now().year
    current_month = datetime.now().month
    if yyyy < current_year or (yyyy == current_year and mm < current_month):
        raise ValueError("Cartão vencido.")
    # Mantém formato MM/AAAA conforme Cielo SDK
    return f"{mm:02d}/{yyyy}"


def _validate_card(card_number: str, cvv: str):
    """Valida número do cartão e CVV com regras básicas."""
    if not card_number or not card_number.isdigit():
        raise ValueError("Número do cartão deve conter apenas dígitos.")
    if len(card_number) < 13 or len(card_number) > 19:
        raise ValueError("Número do cartão inválido (13 a 19 dígitos).")
    # Luhn
    if not _luhn(card_number):
        raise ValueError("Número do cartão inválido (falha na validação Luhn).")
    if not cvv or not cvv.isdigit() or len(cvv) not in (3, 4):
        raise ValueError("CVV inválido (3 ou 4 dígitos).")


def _luhn(num: str) -> bool:
    total = 0
    reverse_digits = list(map(int, reversed(num)))
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _validate_email(email: str):
    import re
    if not email:
        raise ValueError("Email é obrigatório.")
    pattern = r"^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email):
        raise ValueError("Email inválido.")


def _validate_phone(phone: str):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) < 10 or len(digits) > 11:
        raise ValueError("Telefone inválido (informe DDD + número).")


def _validate_cep(cep: str):
    digits = "".join(ch for ch in (cep or "") if ch.isdigit())
    if len(digits) != 8:
        raise ValueError("CEP inválido (8 dígitos).")


def _validate_cpf(cpf: str):
    digits = "".join(ch for ch in (cpf or "") if ch.isdigit())
    if len(digits) != 11:
        raise ValueError("CPF inválido (11 dígitos).")
    if digits == digits[0] * 11:
        raise ValueError("CPF inválido.")
    # Validação de dígitos verificadores
    def calc_dv(digs, weights):
        s = sum(int(d) * w for d, w in zip(digs, weights))
        r = (s * 10) % 11
        return 0 if r == 10 else r
    dv1 = calc_dv(digits[:9], range(10, 1, -1))
    if dv1 != int(digits[9]):
        raise ValueError("CPF inválido.")
    dv2 = calc_dv(digits[:10], range(11, 1, -1))
    if dv2 != int(digits[10]):
        raise ValueError("CPF inválido.")


def cielo_controller():
    """Instancia o controlador da Cielo em produção."""
    environment = Environment(sandbox=False)
    merchant = Merchant(CIELO_MERCHANT_ID, CIELO_MERCHANT_KEY)
    return CieloEcommerce(merchant, environment)


@app.route("/")
def index():
    return render_template(
        "index.html",
        plans=PLANS,
        card_brands=CARD_BRANDS,
        monthly_interest_rate=MONTHLY_INTEREST_RATE,
        max_installments=12,
    )


@app.route("/checkout/<plan_id>", methods=["GET"])
def checkout(plan_id):
    plan = next((p for p in PLANS if p["id"] == plan_id), None)
    if not plan:
        flash("Plano inválido.", "error")
        return redirect(url_for("index"))
    return render_template(
        "checkout.html",
        plan=plan,
        card_brands=CARD_BRANDS,
        monthly_interest_rate=MONTHLY_INTEREST_RATE,
        max_installments=12,
    )


@app.route("/checkout/doacao", methods=["GET"])
def donation_checkout():
    """Checkout dedicado para a doação de R$ 1,00."""
    return render_template(
        "donation_checkout.html",
        card_brands=CARD_BRANDS,
    )


@app.route("/pagar", methods=["POST"])
def pagar():
    try:
        plan_id = request.form.get("plan_id")
        installments = int(request.form.get("installments", "1"))
        # Dados do cliente
        phone = request.form.get("phone")
        email = request.form.get("email")
        cep = request.form.get("cep")
        cpf = request.form.get("cpf")
        holder = request.form.get("holder")
        brand = request.form.get("brand")
        card_number = request.form.get("card_number")
        expiration = request.form.get("expiration")  # MM/YYYY
        cvv = request.form.get("cvv")

        # Busca o plano selecionado
        plan = next((p for p in PLANS if p["id"] == plan_id), None)
        if not plan:
            flash("Plano inválido.", "error")
            return redirect(url_for("index"))

        if installments < 1 or installments > 12:
            flash("Quantidade de parcelas inválida.", "error")
            return redirect(url_for("checkout", plan_id=plan_id))

        # Validações de dados pessoais
        try:
            _validate_phone(phone)
            _validate_email(email)
            _validate_cep(cep)
            _validate_cpf(cpf)
        except ValueError as ve:
            flash(str(ve), "error")
            return redirect(url_for("checkout", plan_id=plan_id))

        # Validações de cartão
        if brand not in CARD_BRANDS:
            flash("Bandeira de cartão inválida.", "error")
            return redirect(url_for("checkout", plan_id=plan_id))
        try:
            normalized_exp = _parse_expiration(expiration)
            _validate_card(card_number, cvv)
        except ValueError as ve:
            flash(str(ve), "error")
            return redirect(url_for("checkout", plan_id=plan_id))

        principal_brl = float(plan["price_brl"])
        # Calcula o valor da parcela com juros
        per_installment = calc_installment_amount(principal_brl, MONTHLY_INTEREST_RATE, installments)
        total_with_interest = round(per_installment * installments, 2)
        amount_cents = BRL_to_cents(total_with_interest)

        # Monta a venda na Cielo
        order_id = str(uuid.uuid4())[:8]
        sale = Sale(order_id)
        sale.customer = Customer(holder or "Cliente")

        credit_card = CreditCard(cvv, brand)
        credit_card.expiration_date = normalized_exp
        credit_card.card_number = card_number
        credit_card.holder = holder

        payment = Payment(amount_cents)
        payment.credit_card = credit_card
        payment.installments = installments
        # Fluxo de captura: imediato ou apenas autorização
        try:
            payment.capture = bool(CIELO_CAPTURE_IMMEDIATELY)
        except Exception:
            pass
        # Solicitar autenticação 3DS se habilitado
        if CIELO_ENABLE_3DS:
            try:
                payment.authenticate = True
            except Exception:
                pass
        # Opcional: identificação curta do estabelecimento na fatura
        try:
            payment.soft_descriptor = "CENTROEDUC"
        except Exception:
            pass
        sale.payment = payment

        cielo = cielo_controller()

        response_create = cielo.create_sale(sale)

        payment_status = getattr(sale.payment, "status", None)
        return_code = getattr(sale.payment, "return_code", None)
        payment_id = sale.payment.payment_id
        authentication_url = getattr(sale.payment, "authentication_url", None)

        # Se captura imediata está ativa, captura no ato
        if CIELO_CAPTURE_IMMEDIATELY:
            response_capture = cielo.capture_sale(payment_id, amount_cents, 0)
            payment_status = 2  # Capturado

        # Dados para comprovante/WhatsApp
        ts = datetime.now().strftime("%d/%m/%Y %H:%M")
        last4 = card_number[-4:] if card_number else ""
        receipt_text = (
            "Comprovante de pagamento - Centro de Consultoria Educacional\n"
            f"Produto: {plan['label']}\n"
            f"Parcelas: {installments}x de R$ {per_installment:.2f}\n"
            f"Bandeira: {brand}\n"
            f"Cartão final: {last4}\n"
            f"Pedido: {order_id}\n"
            f"Pagamento: {payment_id}\n"
            f"Status: Capturado\n"
            f"Data: {ts}\n"
            "CNPJ: 54.863.268/0001-86"
        )

        # Renderiza página de resultado exibindo status e ações conforme necessário
        return render_template(
            "resultado.html",
            success=True,
            message=("Pagamento capturado." if payment_status == 2 else "Pagamento autorizado/pendente."),
            plan_label=plan["label"],
            installments=installments,
            per_installment=per_installment,
            brand=brand,
            masked_card=f"**** **** **** {card_number[-4:]}" if card_number else "",
            order_id=order_id,
            payment_id=payment_id,
            timestamp=ts,
            receipt_text=receipt_text,
            status_code=payment_status,
            status_text=_status_text(payment_status),
            return_code=return_code,
            return_code_text=_return_code_text(return_code),
            auth_url=authentication_url,
            amount_cents=amount_cents,
        )
    except Exception as e:
        return render_template(
            "resultado.html",
            success=False,
            message=f"Falha ao processar pagamento: {e}",
        ), 400


@app.route("/doar", methods=["POST"])
def doar():
    try:
        holder = request.form.get("don_holder")
        brand = request.form.get("don_brand")
        card_number = request.form.get("don_card_number")
        expiration = request.form.get("don_expiration")  # MM/YYYY
        cvv = request.form.get("don_cvv")

        donation_brl = 1.00
        amount_cents = BRL_to_cents(donation_brl)

        order_id = f"don-{str(uuid.uuid4())[:8]}"
        sale = Sale(order_id)
        sale.customer = Customer(holder or "Doador")

        credit_card = CreditCard(cvv, brand)
        # Validações
        if brand not in CARD_BRANDS:
            flash("Bandeira de cartão inválida.", "error")
            return redirect(url_for("index"))
        try:
            normalized_exp = _parse_expiration(expiration)
            _validate_card(card_number, cvv)
        except ValueError as ve:
            flash(str(ve), "error")
            return redirect(url_for("index"))

        credit_card.expiration_date = normalized_exp
        credit_card.card_number = card_number
        credit_card.holder = holder

        payment = Payment(amount_cents)
        payment.credit_card = credit_card
        payment.installments = 1
        # Captura imediata específica para doações
        try:
            payment.capture = bool(CIELO_CAPTURE_IMMEDIATELY_DONATION)
        except Exception:
            pass
        if CIELO_ENABLE_3DS:
            try:
                payment.authenticate = True
            except Exception:
                pass
        try:
            payment.soft_descriptor = "CENTROEDUC"
        except Exception:
            pass
        sale.payment = payment

        cielo = cielo_controller()

        response_create = cielo.create_sale(sale)
        payment_status = getattr(sale.payment, "status", None)
        return_code = getattr(sale.payment, "return_code", None)
        payment_id = sale.payment.payment_id
        authentication_url = getattr(sale.payment, "authentication_url", None)

        if CIELO_CAPTURE_IMMEDIATELY_DONATION:
            cielo.capture_sale(payment_id, amount_cents, 0)
            payment_status = 2

        ts = datetime.now().strftime("%d/%m/%Y %H:%M")
        last4 = card_number[-4:] if card_number else ""
        receipt_text = (
            "Comprovante de pagamento - Centro de Consultoria Educacional\n"
            "Produto: Doação\n"
            f"Parcelas: 1x de R$ {donation_brl:.2f}\n"
            f"Bandeira: {brand}\n"
            f"Cartão final: {last4}\n"
            f"Pedido: {order_id}\n"
            f"Pagamento: {payment_id}\n"
            f"Status: Capturado\n"
            f"Data: {ts}\n"
            "CNPJ: 54.863.268/0001-86"
        )

        return render_template(
            "resultado.html",
            success=True,
            message=("Doação capturada com sucesso." if payment_status == 2 else "Doação autorizada/pendente."),
            plan_label="Doação",
            installments=1,
            per_installment=donation_brl,
            brand=brand,
            masked_card=f"**** **** **** {card_number[-4:]}" if card_number else "",
            order_id=order_id,
            payment_id=payment_id,
            timestamp=ts,
            receipt_text=receipt_text,
            status_code=payment_status,
            status_text=_status_text(payment_status),
            return_code=return_code,
            return_code_text=_return_code_text(return_code),
            auth_url=authentication_url,
            amount_cents=amount_cents,
        )
    except Exception as e:
        return render_template(
            "resultado.html",
            success=False,
            message=f"Falha ao processar doação: {e}",
        ), 400
@app.route("/capturar/<payment_id>", methods=["POST"])
def capturar(payment_id):
    try:
        amount_cents = int(request.form.get("amount_cents"))
        cielo = cielo_controller()
        cielo.capture_sale(payment_id, amount_cents, 0)
        ts = datetime.now().strftime("%d/%m/%Y %H:%M")
        return render_template(
            "resultado.html",
            success=True,
            message="Pagamento capturado com sucesso.",
            payment_id=payment_id,
            timestamp=ts,
        )
    except Exception as e:
        return render_template(
            "resultado.html",
            success=False,
            message=f"Falha ao capturar: {e}",
        ), 400


@app.route("/cancelar/<payment_id>", methods=["POST"])
def cancelar(payment_id):
    try:
        amount_cents = int(request.form.get("amount_cents"))
        cielo = cielo_controller()
        cielo.void_sale(payment_id, amount_cents)
        ts = datetime.now().strftime("%d/%m/%Y %H:%M")
        return render_template(
            "resultado.html",
            success=True,
            message="Pagamento cancelado.",
            payment_id=payment_id,
            timestamp=ts,
        )
    except Exception as e:
        return render_template(
            "resultado.html",
            success=False,
            message=f"Falha ao cancelar: {e}",
        ), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
