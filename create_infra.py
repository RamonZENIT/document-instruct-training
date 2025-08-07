# Criar buckets para PDFs de entrada e resultados
gsutil mb gs://${ai-ml-467520}-pdf-input
gsutil mb gs://${ai-ml-467520}-qa-output
gsutil mb gs://${ai-ml-467520}-function-source

echo "✅ Buckets criados:"
echo "📤 Input: gs://${ai-ml-467520}-pdf-input"
echo "📥 Output: gs://${ai-ml-467520}-qa-output"
