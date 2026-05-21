# Crux Desktop

## Messy CSVs Walk In. Polished Synthetic Data Walks Out.

**Crux Desktop** is a local-first Windows application for cleaning, repairing, and generating financial CSV datasets. It wraps the full Crux interface in a PySide6 desktop shell, starts its own bundled FastAPI engine, detects local Ollama models, and keeps the user’s data on the machine.

> No API used. Your CSV stays local. The rows do the work, not a cloud server.

**Author:** Kartikeya Krishna Mishra

![Crux generation chatbot](docs/assets/crux-generation-chatbot.png)

## Why This Exists

Dirty financial data is boring until it breaks everything. Crux Desktop gives you a local repair bench for CSVs: upload messy rows, inspect what the model understands, clean or repair the dataset, generate synthetic data, and watch every step in PowerShell-style logs.

The desktop version is meant for users who want an installable app instead of a browser-only project. It includes setup screens for local models, an embedded web interface, a runtime log panel, and a release bootstrap installer.

## Core Features

| Feature | What Happens | Output |
| --- | --- | --- |
| Data Cleaning | Removes duplicates, trims text, normalizes blanks, parses numeric/date-like values | Clean CSV |
| Data Repair | Fixes missing values, negative amount-like fields, broken categories, and inconsistent rows | Repaired CSV |
| Data Generation | Trains CTGAN on repaired data, calibrates distributions, preserves rare fraud-like flags | Synthetic CSV |
| Synced Chatbot | Routes user intent into the right page and explains what the app understood | Guided workflow |
| Runtime Logs | Shows start, scan, row-level repair, model interpretation, export, and errors | Transparent execution |
| Model Setup | Detects local Ollama models and offers Llama 3, Qwen, Phi-3, and Mistral choices | Local model control |

## Visual Workflow

```mermaid
flowchart LR
    A["User opens CruxSetup.exe"] --> B["Installer downloads verified package parts"]
    B --> C["SHA256 verification"]
    C --> D["Install to LOCALAPPDATA Programs Crux"]
    D --> E["Create Desktop and Start Menu shortcuts"]
    E --> F["Launch Crux Desktop"]
    F --> G["Detect local Ollama models"]
    G --> H["Start bundled FastAPI engine"]
    H --> I["Use full Crux interface"]
```

## Data Pipeline

```mermaid
flowchart LR
    A["Upload or sample CSV"] --> B["Dataset intelligence panel"]
    B --> C["Cleaning pass"]
    C --> D["Repair pass"]
    D --> E["CTGAN training"]
    E --> F["Synthetic generation"]
    F --> G["Fidelity checks"]
    G --> H["Download CSV"]
```

## What The App Shows

Crux does not quietly mutate data in the shadows. Every page includes a visible interpretation layer:

| Panel | Purpose |
| --- | --- |
| User Query | Shows what the user asked for |
| Problem Interpreted | Explains what Crux thinks is wrong or requested |
| Model Understanding | Summarizes columns, missing values, duplicates, and negative amount-like fields |
| Expected Output | Tells the user what should change after the run |
| Before vs After | Displays row samples and metric changes |
| Runtime Logs | Shows the exact local process as it runs |

## Folder Structure

```text
app/
  desktop_launcher.py                 PySide6 desktop shell and local engine launcher
  bundled_web/                        Independent bundled Crux web/backend app
  model_catalog.json                  Local model choices shown in setup
  installer/                          Inno and GitHub bootstrap installer sources
  installer/bootstrap/                CruxSetup.exe bootstrap source
  docs/assets/                        README visuals
  verification/                       Local verification outputs, ignored by git
  Crux.spec                           PyInstaller build spec
  build_installer.ps1                 Repeatable Windows build script
  requirements.txt                    Desktop and bundled engine dependencies
```

`app/bundled_web` is intentionally independent from the web repository. The desktop app keeps working even when the web version lives in a separate GitHub repo.

## Install From GitHub Release

Download:

[CruxSetup.exe](https://github.com/KartikeyaM2007/CRUX-AppVersion/releases/download/v1.0.0/CruxSetup.exe)

The setup app:

1. Downloads the verified split package from GitHub Releases.
2. Verifies SHA256 checksums.
3. Installs Crux to `%LOCALAPPDATA%\Programs\Crux`.
4. Creates Desktop and Start Menu shortcuts.
5. Launches Crux Desktop.

The split `.zip.part001` and `.zip.part002` files are kept in the release because GitHub has a 2 GB asset limit. Normal users should download `CruxSetup.exe`.

## Run From Source

```powershell
cd app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python desktop_launcher.py
```

Recommended local model:

```powershell
ollama pull llama3
ollama run llama3
```

## Verify

```powershell
python desktop_launcher.py --self-test
```

Full CSV verification from the parent workspace:

```powershell
python app\verify_features.py C:\Users\USER\Downloads\dirty_financial_transactions.csv
```

The verifier checks that real transformations happen:

| Check | Verified Behavior |
| --- | --- |
| Cleaning | Removes missing values and duplicates from test data |
| Repair | Fixes nulls, duplicates, and negative amount-like fields |
| Generation | Trains CTGAN on repaired data |
| Chatbot Generation | Generates the requested row count |
| Export | Produces downloadable CSV files |

## Build Portable Windows App

```powershell
cd app
.\build_installer.ps1 -SkipInno
```

Outputs:

```text
app/dist/Crux/                         Portable app folder
app/release/Crux-portable-windows.zip  Local portable package
```

## Build Release Bootstrap Installer

```powershell
cd app
.\installer\bootstrap\build_bootstrap_installer.ps1
```

Output:

```text
app/release/CruxSetup.exe
```

## Build Inno Setup Installer

Install Inno Setup, then run:

```powershell
cd app
.\build_installer.ps1
```

If `ISCC.exe` is available on `PATH`, the script also creates:

```text
app/release/CruxSetup-0.1.0.exe
```

## Release Notes

The GitHub release contains:

| Asset | Use |
| --- | --- |
| `CruxSetup.exe` | Recommended installer |
| `Crux-portable-windows.zip.part001` | Portable package part 1 |
| `Crux-portable-windows.zip.part002` | Portable package part 2 |
| `Crux-portable-windows.SHA256.txt` | Integrity and reassembly notes |
| `Crux.exe` | Legacy single executable launcher asset |

## Privacy

Crux is designed local-first. Cleaning, repair, generation, and evaluation run locally. LLM-assisted repair uses the user’s local Ollama runtime when available.
