#!/usr/bin/env python3
"""View extracted contact data from Excel file."""

import pandas as pd
import sys

def view_excel(file_path):
    """Display the contact data from the Excel file."""
    try:
        # Read the "All Leads" sheet
        df = pd.read_excel(file_path, sheet_name="All Leads")
        
        print(f"📊 Contact Data from {file_path}")
        print("=" * 80)
        
        # Show key contact columns
        contact_columns = ['name', 'email', 'phone', 'apollo_title', 'apollo_organization', 'lead_score', 'score_tier']
        
        if all(col in df.columns for col in contact_columns):
            contact_df = df[contact_columns]
            
            print(f"Found {len(contact_df)} prospects:\n")
            
            for idx, row in contact_df.iterrows():
                print(f"{idx + 1}. {row['name']}")
                print(f"   📧 Email: {row['email'] or 'Not available'}")
                print(f"   📞 Phone: {row['phone'] or 'Not available'}")
                print(f"   💼 Title: {row['apollo_title']}")
                print(f"   🏢 Company: {row['apollo_organization']}")
                print(f"   ⭐ Score: {row['lead_score']} ({row['score_tier']})")
                print()
        else:
            print("Available columns:")
            print(df.columns.tolist())
            print("\nFirst few rows:")
            print(df.head())
            
    except Exception as e:
        print(f"Error reading Excel file: {e}")

if __name__ == "__main__":
    file_path = "data/output/investor_leads_20260515_195234.xlsx"
    view_excel(file_path)