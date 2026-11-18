# FreeData.AI — User Guide

## 1. Accessing the Platform & PRO Features
- Open the FreeData.AI web application.
- For PRO Market Study PDFs and LLM synthesis, click the **PRO / Clé Partenaire** badge in the top bar and enter your partner key (`X-Premium-Key`).

## 2. Creating & Managing Projects (**Espace Projets**)
1. Click the **Espace Projets** icon (`folder_special`) in the top bar.
2. Click **+** to create a project with a name and description.
3. Use the project menu (`⋮`) to **Rename**, **Archive/Restore**, or **Delete** (with confirmation).
4. Click **▶ (Reprendre)** to resume a project in the chat workspace.

## 3. Using the AI Assistant & Refining Assumptions
- Describe your corridor, commodity, capital, and promoter name (e.g., *"Négoce de mil de Lac vers Batha avec 1 000 000 XAF, promoteur : Moussa, inclure SWOT"*).
- **Correcting parameters**: Use phrases like *"Finalement budget 1 200 000 XAF"*, *"BFR constant"*, or *"CAPEX = 0"*. The persistent `StudyContext` updates only the changed field without erasing earlier instructions.
- **Requesting/excluding sections**: Specify *"Inclure SWOT et PESTEL"* or *"Exclure projection 6 mois"*.

## 4. Generating, Validating & Downloading PDFs
1. Once required parameters are known, click **Télécharger Étude PDF (PRO)** below the assistant reply.
2. The backend runs the Phase 4 QA validator; if a critical check fails, the UI displays the exact required corrections (`422`).
3. Otherwise, the institutional PDF (with logo, Table of Contents, cash-flow chart, provenance table, and 24h–48h terrain checklist) downloads automatically.

## 5. Version History & Comparison
- Inside **Espace Projets**, click the history icon on any project to view studies and versions (`v1`, `v2`, ...), download any previous PDF, or compare `v1` vs `v2`.

