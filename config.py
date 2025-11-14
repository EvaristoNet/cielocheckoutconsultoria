"""
Configurações do sistema "Centro de Consultoria Educacional".
ATENÇÃO: Em produção, prefira variáveis de ambiente e cofre de segredos.
"""

# Chaves Cielo fornecidas pelo usuário (produção)
CIELO_MERCHANT_ID = "ab793efc-3fca-422e-b799-ce2dae1a61cf"
CIELO_MERCHANT_KEY = "ShZShjv9PqrOFz8FO1IWEj645X5cDkhQRs8wyqlk"

# Juros mensais para parcelamento (moderado, não exagerado)
# Ex.: 1.5% ao mês
MONTHLY_INTEREST_RATE = 0.015

# Fluxo de captura/autorização e 3DS (ajuste conforme regras da adquirente)
# Se False, primeiro autoriza e captura depois (útil em antifraude ou 3DS)
CIELO_CAPTURE_IMMEDIATELY = False
# Solicitar autenticação 3DS se disponível (a adquirente pode retornar URL)
CIELO_ENABLE_3DS = True

# Captura imediata apenas para doações
CIELO_CAPTURE_IMMEDIATELY_DONATION = True