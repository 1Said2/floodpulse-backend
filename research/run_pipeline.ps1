$python = ".\venv\Scripts\python.exe"
$csv_file = "C:\Users\micha\.gemini\antigravity-ide\brain\91d1d6a8-6e87-4801-8f0f-75b091b84d10\scratch\inamhi_1994_2013.csv"

Write-Host "Starting Step 1: Extraction..."
& $python "C:\Users\micha\.gemini\antigravity-ide\brain\91d1d6a8-6e87-4801-8f0f-75b091b84d10\scratch\extract_20_years.py"

if (-not (Test-Path $csv_file)) {
    Write-Host "Error: Extraction failed, CSV not generated."
    exit 1
}

Write-Host "Starting IMERG Batch Fetching (Step 2)..."
$script = "C:\Users\micha\.gemini\antigravity-ide\brain\91d1d6a8-6e87-4801-8f0f-75b091b84d10\scratch\fetch_imerg_batch.py"

$max_retries = 200
$retry_count = 0
while ($retry_count -lt $max_retries) {
    & $python $script
    if ($LASTEXITCODE -eq 0) {
        Write-Host "IMERG Fetching completed successfully."
        break
    } else {
        Write-Host "IMERG script crashed or hit rate limits (Exit Code $LASTEXITCODE). Retrying in 15 seconds..."
        $retry_count++
        Start-Sleep -Seconds 15
    }
}

Write-Host "Running Final Regression (Step 3)..."
$reg_script = "C:\Users\micha\.gemini\antigravity-ide\brain\91d1d6a8-6e87-4801-8f0f-75b091b84d10\scratch\final_regression.py"
& $python $reg_script
Write-Host "Pipeline completely finished!"
