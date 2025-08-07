# 1. Instalar Google Cloud SDK (se não tiver)
# Windows: https://cloud.google.com/sdk/docs/install
# Mac: brew install google-cloud-sdk
# Linux: curl https://sdk.cloud.google.com | bash

# 2. Fazer login
gcloud auth login

# 3. Criar novo projeto (substitua por um ID único)
export PROJECT_ID="pdf-qa-generator-$(date +%s)"
gcloud projects create $PROJECT_ID --name="PDF QA Generator"

# 4. Configurar projeto como padrão
gcloud config set project $PROJECT_ID

# 5. Habilitar billing (OBRIGATÓRIO)
# Vá para: https://console.cloud.google.com/billing
# Associe seu projeto a uma conta de billing

# 6. Definir região padrão
export REGION="us-central1"
gcloud config set compute/region $REGION
