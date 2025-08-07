# 🚀 Guia Completo: PDF para Q&A no GCP do Zero
## 📋 FASE 1: PREPARAÇÃO INICIAL
Pré-requisitos

Conta Google Cloud Platform
Cartão de crédito cadastrado (para ativar recursos)
Google Cloud SDK instalado localmente

### 1.1 Configuração Inicial do Projeto
bash# 1. Instalar Google Cloud SDK (se não tiver)
### Windows: https://cloud.google.com/sdk/docs/install
### Mac: brew install google-cloud-sdk
### Linux: curl https://sdk.cloud.google.com | bash

## 2. Fazer login
gcloud auth login

## 3. Criar novo projeto (substitua por um ID único)
export PROJECT_ID="pdf-qa-generator-$(date +%s)"
gcloud projects create $PROJECT_ID --name="PDF QA Generator"

## 4. Configurar projeto como padrão
gcloud config set project $PROJECT_ID

## 5. Habilitar billing (OBRIGATÓRIO)
### Vá para: https://console.cloud.google.com/billing
### Associe seu projeto a uma conta de billing

## 6. Definir região padrão

export REGION="us-central1"
gcloud config set compute/region $REGION
1.2 Habilitar APIs Necessárias
bash# Habilitar todas as APIs necessárias (pode demorar alguns minutos)
echo "⏳ Habilitando APIs..."
gcloud services enable documentai.googleapis.com
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable storage.googleapis.com
gcloud services enable bigquery.googleapis.com
gcloud services enable aiplatform.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable eventarc.googleapis.com

echo "✅ APIs habilitadas!"
📁 FASE 2: CRIAÇÃO DA INFRAESTRUTURA
2.1 Criar Buckets de Storage
bash# Criar buckets para PDFs de entrada e resultados
gsutil mb gs://${PROJECT_ID}-pdf-input
gsutil mb gs://${PROJECT_ID}-qa-output
gsutil mb gs://${PROJECT_ID}-function-source

echo "✅ Buckets criados:"
echo "📤 Input: gs://${PROJECT_ID}-pdf-input"
echo "📥 Output: gs://${PROJECT_ID}-qa-output"
2.2 Configurar Document AI
bash# Criar processador Document AI
echo "⏳ Criando Document AI Processor..."

# Via gcloud (método simples)
PROCESSOR_ID=$(gcloud ai document-processors create \
  --location=$REGION \
  --display-name="PDF-QA-Extractor" \
  --type="OCR_PROCESSOR" \
  --format="value(name)" | cut -d'/' -f6)

echo "✅ Document AI Processor criado: $PROCESSOR_ID"
echo "💾 Salvando PROCESSOR_ID..."
echo $PROCESSOR_ID > processor_id.txt
2.3 Criar Dataset BigQuery
bash# Criar dataset para armazenar resultados
bq mk --dataset --location=$REGION \
  --description="Dataset para Q&A pairs gerados" \
  ${PROJECT_ID}:qa_training_data

# Criar tabela
bq mk --table ${PROJECT_ID}:qa_training_data.generated_qa_pairs \
  instruction:STRING,output:STRING,content:STRING,source_file:STRING,chunk_id:INTEGER,created_at:TIMESTAMP

echo "✅ BigQuery dataset e tabela criados!"
💻 FASE 3: DESENVOLVIMENTO DA CLOUD FUNCTION
3.1 Criar Estrutura de Arquivos
bash# Criar diretório do projeto
mkdir pdf-qa-generator
cd pdf-qa-generator

# Criar arquivos necessários
touch main.py
touch requirements.txt
touch .env
3.2 Arquivo requirements.txt
txtgoogle-cloud-documentai==2.25.0
google-cloud-storage==2.13.0
google-cloud-bigquery==3.15.0
google-cloud-aiplatform==1.42.1
pandas==2.0.3
vertexai==1.42.1
functions-framework==3.5.0
3.3 Arquivo main.py (Cloud Function)
pythonimport os
import json
import pandas as pd
from typing import List, Dict
from datetime import datetime
import logging
import re

# Google Cloud imports
from google.cloud import storage
from google.cloud import documentai
from google.cloud import bigquery
import vertexai
from vertexai.preview.generative_models import GenerativeModel

# Configurações
PROJECT_ID = os.environ.get('GCP_PROJECT')
LOCATION = os.environ.get('FUNCTION_REGION', 'us-central1')
PROCESSOR_ID = os.environ.get('PROCESSOR_ID')
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET')
BIGQUERY_DATASET = os.environ.get('BIGQUERY_DATASET', 'qa_training_data')

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def process_pdf_upload(cloud_event):
    """
    Cloud Function principal - triggered por upload de PDF
    """
    
    # Extrair informações do evento
    data = cloud_event.data
    bucket_name = data['bucket']
    file_name = data['name']
    
    logger.info(f"📄 Processando: {file_name} do bucket: {bucket_name}")
    
    # Verificar se é PDF
    if not file_name.lower().endswith('.pdf'):
        logger.info(f"❌ Arquivo {file_name} não é PDF. Ignorando.")
        return 'OK'
    
    try:
        # 1. Extrair texto do PDF
        logger.info("🔍 Extraindo texto com Document AI...")
        document_text = extract_text_from_pdf(bucket_name, file_name)
        
        if not document_text or len(document_text) < 100:
            logger.error(f"❌ Texto extraído muito pequeno: {len(document_text)} chars")
            return 'ERROR'
        
        # 2. Dividir em chunks
        logger.info("✂️ Dividindo documento em chunks...")
        chunks = chunk_document(document_text)
        logger.info(f"📝 Criados {len(chunks)} chunks")
        
        # 3. Gerar Q&A para cada chunk
        logger.info("🤖 Gerando Q&A com Gemini...")
        all_qa_pairs = []
        
        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 200:  # Skip chunks muito pequenos
                continue
                
            qa_pairs = generate_qa_from_chunk(chunk, i, file_name)
            all_qa_pairs.extend(qa_pairs)
            logger.info(f"✅ Chunk {i}: {len(qa_pairs)} Q&A gerados")
        
        if not all_qa_pairs:
            logger.error("❌ Nenhum Q&A gerado!")
            return 'ERROR'
        
        # 4. Salvar resultados
        logger.info("💾 Salvando resultados...")
        save_results(all_qa_pairs, file_name)
        
        logger.info(f"🎉 Processamento concluído! {len(all_qa_pairs)} Q&A pairs gerados")
        return 'OK'
        
    except Exception as e:
        logger.error(f"💥 Erro no processamento: {str(e)}")
        raise e

def extract_text_from_pdf(bucket_name: str, file_name: str) -> str:
    """Extrai texto usando Document AI"""
    
    try:
        # Cliente Document AI
        client = documentai.DocumentProcessorServiceClient()
        name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)
        
        # Baixar PDF do Storage
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        file_content = blob.download_as_bytes()
        
        # Processar documento
        raw_document = documentai.RawDocument(
            content=file_content,
            mime_type="application/pdf"
        )
        
        request = documentai.ProcessRequest(
            name=name,
            raw_document=raw_document
        )
        
        result = client.process_document(request=request)
        return result.document.text
        
    except Exception as e:
        logger.error(f"Erro na extração: {str(e)}")
        raise e

def chunk_document(text: str, chunk_size: int = 3000, overlap: int = 300) -> List[str]:
    """Divide documento em chunks com sobreposição"""
    
    chunks = []
    
    # Primeiro, dividir por seções grandes (parágrafos duplos)
    sections = re.split(r'\n\s*\n', text)
    
    current_chunk = ""
    
    for section in sections:
        if len(current_chunk) + len(section) < chunk_size:
            current_chunk += section + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = section + "\n\n"
    
    # Adicionar último chunk
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

def generate_qa_from_chunk(chunk: str, chunk_id: int, source_file: str) -> List[Dict]:
    """Gera Q&A usando Gemini"""
    
    try:
        # Inicializar Vertex AI
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        model = GenerativeModel("gemini-1.5-pro")
        
        prompt = f"""
Você é um especialista em criar datasets de treino para modelos de linguagem.

Com base no seguinte trecho de documento, crie EXATAMENTE 8 pares de pergunta-resposta que sejam:

1. ESPECÍFICAS ao conteúdo fornecido (não genéricas)
2. VARIADAS em tipo:
   - Definições e conceitos
   - Processos e procedimentos  
   - Causas e efeitos
   - Comparações
   - Análises e interpretações
   - Dados específicos e números
3. CLARAS e bem formuladas
4. Com respostas COMPLETAS e PRECISAS baseadas no texto

IMPORTANTE: Responda APENAS com um JSON válido:
[
    {{"instruction": "pergunta específica 1", "output": "resposta completa 1"}},
    {{"instruction": "pergunta específica 2", "output": "resposta completa 2"}},
    {{"instruction": "pergunta específica 3", "output": "resposta completa 3"}},
    {{"instruction": "pergunta específica 4", "output": "resposta completa 4"}},
    {{"instruction": "pergunta específica 5", "output": "resposta completa 5"}},
    {{"instruction": "pergunta específica 6", "output": "resposta completa 6"}},
    {{"instruction": "pergunta específica 7", "output": "resposta completa 7"}},
    {{"instruction": "pergunta específica 8", "output": "resposta completa 8"}}
]

Trecho do documento:
{chunk}
"""
        
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.8,
                "top_p": 0.9,
                "max_output_tokens": 8000,
            }
        )
        
        # Limpar resposta
        response_text = response.text.strip()
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        
        # Parse JSON
        qa_pairs = json.loads(response_text)
        
        # Adicionar metadata
        for qa in qa_pairs:
            qa['chunk_id'] = chunk_id
            qa['source_file'] = source_file
            qa['content'] = chunk
            qa['created_at'] = datetime.utcnow().isoformat()
        
        return qa_pairs
        
    except json.JSONDecodeError as e:
        logger.error(f"Erro JSON para chunk {chunk_id}: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Erro Gemini para chunk {chunk_id}: {str(e)}")
        return []

def save_results(qa_pairs: List[Dict], source_file: str):
    """Salva no Storage e BigQuery"""
    
    # DataFrame
    df = pd.DataFrame(qa_pairs)
    
    # Nome do arquivo
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"qa_dataset_{source_file.replace('.pdf', '')}_{timestamp}.csv"
    
    # Salvar no Storage
    storage_client = storage.Client()
    bucket = storage_client.bucket(OUTPUT_BUCKET)
    blob = bucket.blob(f"datasets/{csv_filename}")
    
    csv_string = df.to_csv(index=False)
    blob.upload_from_string(csv_string, content_type='text/csv')
    
    logger.info(f"💾 CSV salvo: gs://{OUTPUT_BUCKET}/datasets/{csv_filename}")
    
    # Salvar no BigQuery
    try:
        client = bigquery.Client(project=PROJECT_ID)
        table_id = f"{PROJECT_ID}.{BIGQUERY_DATASET}.generated_qa_pairs"
        
        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",
            autodetect=True
        )
        
        job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
        job.result()
        
        logger.info(f"📊 Dados salvos no BigQuery: {table_id}")
        
    except Exception as e:
        logger.error(f"Erro BigQuery: {str(e)}")
🚀 FASE 4: DEPLOY DA SOLUÇÃO
4.1 Deploy da Cloud Function
bash# Voltar para o diretório do projeto
cd pdf-qa-generator

# Obter PROCESSOR_ID salvo
PROCESSOR_ID=$(cat ../processor_id.txt)

# Deploy da função
gcloud functions deploy pdf-qa-processor \
  --gen2 \
  --runtime=python311 \
  --region=$REGION \
  --source=. \
  --entry-point=process_pdf_upload \
  --trigger-bucket=${PROJECT_ID}-pdf-input \
  --memory=8GiB \
  --timeout=3600 \
  --max-instances=10 \
  --set-env-vars="PROCESSOR_ID=${PROCESSOR_ID},OUTPUT_BUCKET=${PROJECT_ID}-qa-output"

echo "✅ Cloud Function deployada!"
echo "🎯 Trigger: gs://${PROJECT_ID}-pdf-input"
4.2 Configurar Permissões
bash# Garantir permissões corretas
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

# Permissão para Vertex AI
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Permissão para Document AI
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/documentai.apiUser"

echo "✅ Permissões configuradas!"
🧪 FASE 5: TESTE DA SOLUÇÃO
5.1 Teste com PDF de Exemplo
bash# Baixar PDF de teste
curl -o teste.pdf "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"

# Fazer upload (isso vai triggerar a função automaticamente)
gsutil cp teste.pdf gs://${PROJECT_ID}-pdf-input/

echo "📤 PDF enviado! Aguarde o processamento..."
echo "👀 Acompanhe os logs:"
echo "gcloud functions logs read pdf-qa-processor --region=$REGION --limit=50"
5.2 Verificar Resultados
bash# Verificar arquivos gerados
echo "📁 Arquivos gerados:"
gsutil ls gs://${PROJECT_ID}-qa-output/datasets/

# Verificar dados no BigQuery
echo "📊 Dados no BigQuery:"
bq query --use_legacy_sql=false "
SELECT 
  source_file,
  COUNT(*) as qa_pairs,
  MIN(created_at) as first_generated,
  MAX(created_at) as last_generated
FROM \`${PROJECT_ID}.qa_training_data.generated_qa_pairs\`
GROUP BY source_file
"
📊 FASE 6: MONITORAMENTO E OTIMIZAÇÃO
6.1 Dashboard de Monitoramento
bash# Criar alertas
gcloud alpha monitoring policies create --policy-from-file=- <<EOF
{
  "displayName": "PDF QA Function Errors",
  "conditions": [
    {
      "displayName": "Function error rate",
      "conditionThreshold": {
        "filter": "resource.type=\"cloud_function\" AND resource.label.function_name=\"pdf-qa-processor\"",
        "comparison": "COMPARISON_GREATER_THAN",
        "thresholdValue": 0.1
      }
    }
  ]
}
EOF
6.2 Scripts de Manutenção
bash# Script para limpeza automática (opcional)
cat > cleanup.sh << 'EOF'
#!/bin/bash
# Remove arquivos antigos (30+ dias)
gsutil -m rm gs://${PROJECT_ID}-pdf-input/**
gsutil lifecycle set - gs://${PROJECT_ID}-qa-output << LIFECYCLE
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 90}
      }
    ]
  }
}
LIFECYCLE
EOF

chmod +x cleanup.sh
🎉 SOLUÇÃO COMPLETA!
Como Usar:

Upload de PDF: gsutil cp seu_documento.pdf gs://${PROJECT_ID}-pdf-input/
Aguardar processamento: 2-10 minutos dependendo do tamanho
Baixar resultados: gsutil cp gs://${PROJECT_ID}-qa-output/datasets/*.csv ./

Monitoramento:

Logs: gcloud functions logs read pdf-qa-processor --region=$REGION
BigQuery: Console do BigQuery para análises
Storage: Console do Cloud Storage para arquivos

Custos Estimados (por PDF de 100 páginas):

Document AI: ~$1.50
Vertex AI (Gemini): ~$0.50
Cloud Functions: ~$0.10
Storage/BigQuery: ~$0.05
Total: ~$2.15 por documento
