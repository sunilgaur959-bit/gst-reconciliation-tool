
import pandas as pd
import os

if not os.path.exists('static/files'):
    os.makedirs('static/files')

data = {
    'GSTIN': ['27AAAAA1234A1Z5', '27BBBBB5678B1Z1'],
    'Supplier Name': ['Sample Supplier 1', 'Sample Supplier 2'],
    'Invoice No': ['INV-001', 'INV-002'],
    'Invoice Date': ['01-01-2023', '05-01-2023'],
    'Integrated Tax': [1000, 0],
    'Central Tax': [0, 500],
    'State Tax': [0, 500],
    'Taxable Value': [5000, 2500]
}

df = pd.DataFrame(data)

with pd.ExcelWriter('static/files/gst_reco_template.xlsx', engine='openpyxl') as writer:
    df.to_excel(writer, sheet_name='GSTR_2B', index=False)
    df.to_excel(writer, sheet_name='BOOKS', index=False)

print("Template created successfully.")
