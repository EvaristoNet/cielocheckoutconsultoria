def calc_installment_amount(principal_brl: float, monthly_rate: float, installments: int) -> float:
    """
    Calcula o valor de cada parcela usando a fórmula de financiamento (Price):
    parcela = P * (i*(1+i)^n) / ((1+i)^n - 1)

    - principal_brl: valor principal em BRL
    - monthly_rate: taxa mensal (ex.: 0.015 para 1.5%)
    - installments: número de parcelas (1 a 12)
    """
    if installments <= 1 or monthly_rate <= 0:
        return round(principal_brl, 2)
    i = monthly_rate
    n = installments
    factor = (i * (1 + i) ** n) / (((1 + i) ** n) - 1)
    return round(principal_brl * factor, 2)


def BRL_to_cents(amount_brl: float) -> int:
    """Converte BRL para centavos inteiros (ex.: 10.00 -> 1000)."""
    return int(round(amount_brl * 100))