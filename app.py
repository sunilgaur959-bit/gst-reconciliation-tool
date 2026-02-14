import os
import time
import re
import pandas as pd
from flask import Flask, render_template, request, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename
import io

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'downloads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==============================
# RECONCILIATION LOGIC
# ==============================

def read_sheet_safely(file_path, sheet):
    # Determine engine based on extension
    engine = 'openpyxl' if file_path.endswith('.xlsx') else 'xlrd'
    
    try:
        raw = pd.read_excel(file_path, sheet_name=sheet, header=None, engine=engine)
    except ValueError:
       # Sheet not found
       raise Exception(f"Sheet '{sheet}' not found in the uploaded file.")

    header_row = None
    # Look for header row in first 20 rows
    for i in range(min(20, len(raw))):
        row_values = raw.iloc[i].astype(str).tolist()
        row_text = " ".join(row_values).lower()
        # Heuristic to find header
        if ("supplier" in row_text or "party" in row_text) and ("gst" in row_text or "invoice" in row_text):
            header_row = i
            break
        # Fallback if just generic terms found, try to be more lenient if above fails
        if "supplier" in row_text or "party" in row_text:
             header_row = i # Potential candidate, but keep looking? No, usually first match is best.
             break

    if header_row is None:
        # If strictly "supplier" or "party" not found, try finding "Invoice"
        for i in range(min(20, len(raw))):
             row_text = " ".join(raw.iloc[i].astype(str)).lower()
             if "invoice" in row_text and ("date" in row_text or "no" in row_text):
                 header_row = i
                 break
    
    if header_row is None:
        # Default to 0 if all else fails, but this might be risky
        header_row = 0

    return pd.read_excel(file_path, sheet_name=sheet, header=header_row, engine=engine)

def normalise_columns(df):
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace("\u00a0", "", regex=True)
        .str.replace("\n", "", regex=True)
        .str.replace("\r", "", regex=True)
    )
    return df

def map_columns(df):
    mapping = {
        "Supplier Name": "Supplier_Name",
        "Party Name": "Supplier_Name",
        "Vendor Name": "Supplier_Name",
        "Name of the Supplier": "Supplier_Name",

        "Invoice No": "Invoice_No",
        "Invoice Number": "Invoice_No",
        "Bill No": "Invoice_No",
        "Document Number": "Invoice_No",

        "Integrated Tax": "IGST",
        "Central Tax": "CGST",
        "State Tax": "SGST",
        "IGST Amount": "IGST",
        "CGST Amount": "CGST",
        "SGST Amount": "SGST",
        
        "GSTIN": "GSTIN",
        "GSTIN of Supplier": "GSTIN",
        "Supplier GSTIN": "GSTIN",
        "GST Number": "GSTIN",
    }
    # Case insensitive mapping attempt
    new_cols = {}
    for col in df.columns:
        for k, v in mapping.items():
            if k.lower() == col.lower():
                new_cols[col] = v
                break
    df.rename(columns=new_cols, inplace=True)
    return df

def clean_supplier(x):
    if pd.isna(x):
        return ""
    return (
        str(x).upper()
        .replace("PVT", "")
        .replace("LTD", "")
        .replace("LIMITED", "")
        .replace("LLP", "")
        .replace(".", "")
        .strip()
    )

def clean_invoice(x):
    if pd.isna(x):
        return ""
    # Remove non-alphanumeric except maybe / or - if needed, but original script removed everything
    return re.sub(r"[^A-Z0-9]", "", str(x).upper())

def tax_structure(r):
    # Ensure columns exist, default to 0 if not
    igst = r.get("IGST", 0)
    cgst = r.get("CGST", 0)
    sgst = r.get("SGST", 0)
    
    if igst > 0 and cgst == 0 and sgst == 0:
        return "IGST"
    if igst == 0 and cgst > 0 and sgst > 0:
        return "CGST_SGST"
    return "OTHER"

def process_reconciliation(input_path, output_path):
    TOLERANCE = 1

    try:
        # 1. Read Sheets
        gstr2b = read_sheet_safely(input_path, "GSTR_2B")
        books = read_sheet_safely(input_path, "BOOKS")
    except Exception as e:
        return str(e)

    # 2. Normalise & Map
    gstr2b = map_columns(normalise_columns(gstr2b))
    books = map_columns(normalise_columns(books))

    # 3. Clean Data
    for df in [gstr2b, books]:
        if "Invoice_No" not in df.columns:
            df["Invoice_No"] = ""
        if "Supplier_Name" not in df.columns:
             df["Supplier_Name"] = "" # Handle missing supplier name column
        if "GSTIN" not in df.columns:
             df["GSTIN"] = ""
             
        # Ensure regex columns are present
        for col in ["IGST", "CGST", "SGST"]:
            if col not in df.columns:
                df[col] = 0

        df["Invoice_No"] = df["Invoice_No"].astype(str)
        df["Invoice_No_CLEAN"] = df["Invoice_No"].apply(clean_invoice)
        df["Supplier_Name_CLEAN"] = df["Supplier_Name"].apply(clean_supplier)

        for col in ["IGST", "CGST", "SGST"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        df["RECO_REMARK"] = "NOT MATCHED"
        df["USED"] = False
    
    # 4. Tax Structure
    gstr2b["TAX_STRUCTURE"] = gstr2b.apply(tax_structure, axis=1)
    books["TAX_STRUCTURE"] = books.apply(tax_structure, axis=1)

    # 5A. Invoice Number Match
    books_grouped = books[books["Invoice_No_CLEAN"] != ""].groupby("Invoice_No_CLEAN")

    for inv_no, grp in books_grouped:
        igst_sum = grp["IGST"].sum()
        cgst_sum = grp["CGST"].sum()
        sgst_sum = grp["SGST"].sum()
        tax_struct = grp.iloc[0]["TAX_STRUCTURE"]

        candidates = gstr2b[
            (~gstr2b["USED"]) &
            (gstr2b["Invoice_No_CLEAN"] == inv_no) &
            (gstr2b["TAX_STRUCTURE"] == tax_struct)
        ]

        for j, g in candidates.iterrows():
            if (
                abs(g["IGST"] - igst_sum) <= TOLERANCE and
                abs(g["CGST"] - cgst_sum) <= TOLERANCE and
                abs(g["SGST"] - sgst_sum) <= TOLERANCE
            ):
                books.loc[grp.index, ["RECO_REMARK", "USED"]] = ["MATCHED", True]
                gstr2b.loc[j, ["RECO_REMARK", "USED"]] = ["MATCHED", True]
                break

    # 5B. Fallback Match
    unmatched_books = books[~books["USED"]]
    for i, b in unmatched_books.iterrows():
        candidates = gstr2b[
            (~gstr2b["USED"]) &
            (gstr2b["TAX_STRUCTURE"] == b["TAX_STRUCTURE"]) &
            (abs(gstr2b["IGST"] - b["IGST"]) <= TOLERANCE) &
            (abs(gstr2b["CGST"] - b["CGST"]) <= TOLERANCE) &
            (abs(gstr2b["SGST"] - b["SGST"]) <= TOLERANCE)
        ]

        if len(candidates) >= 1:
            j = candidates.index[0]
            books.loc[i, ["RECO_REMARK", "USED"]] = ["MATCHED", True]
            gstr2b.loc[j, ["RECO_REMARK", "USED"]] = ["MATCHED", True]

    # 6. Write Output
    drop_cols = ["Invoice_No_CLEAN", "Supplier_Name_CLEAN", "TAX_STRUCTURE", "USED"]
    # Ensure GSTIN is kept (it's not in drop_cols, so it should be fine).
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        gstr2b.drop(columns=drop_cols, errors="ignore").to_excel(writer, sheet_name="GSTR_2B", index=False)
        books.drop(columns=drop_cols, errors="ignore").to_excel(writer, sheet_name="BOOKS", index=False)
    
    return None # Success

# ==============================
# ROUTES
# ==============================

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            input_path = os.path.join(UPLOAD_FOLDER, filename)
            output_filename = f"Reconciled_{filename}"
            output_path = os.path.join(OUTPUT_FOLDER, output_filename)
            
            file.save(input_path)
            
            # Process
            error = process_reconciliation(input_path, output_path)
            
            if error:
                flash(f"Error Processing File: {error}")
                return redirect(request.url)
            
            
            return send_file(output_path, as_attachment=True)
            
    return render_template('index.html')

@app.route('/download-template')
def download_template():
    return send_file('static/files/gst_reco_template.xlsx', as_attachment=True, download_name='GST_Reco_Template.xlsx')

if __name__ == '__main__':
    import webbrowser
    from threading import Timer
    
    def open_browser():
        if not os.environ.get("WERKZEUG_RUN_MAIN"):
            webbrowser.open_new('http://127.0.0.1:5000/')

    Timer(1, open_browser).start()
    app.run(debug=True, port=5000)
