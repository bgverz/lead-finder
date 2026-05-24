#!/usr/bin/env python3
"""Test script to demonstrate email and phone extraction from Apollo."""

import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from lead_pipeline.utils.config import load_config
from lead_pipeline.enrichment.apollo import ApolloClient

def main():
    """Test Apollo email/phone extraction."""
    load_dotenv()
    
    # Load config
    config = load_config("config/config.yaml")
    
    # Create Apollo client
    client = ApolloClient(config)
    
    print("Testing Apollo email/phone extraction...")
    print(f"Contact reveal enabled: {config.apollo.reveal_contacts}")
    print(f"Max reveals per run: {config.apollo.max_reveals_per_run}")
    
    # Search for people
    people = client.search_people()
    
    print(f"\nFound {len(people)} prospects:")
    print("-" * 80)
    
    for i, person in enumerate(people[:3], 1):  # Show first 3
        print(f"{i}. {person.display_name}")
        print(f"   Title: {person.title}")
        print(f"   Company: {person.organization_name}")
        print(f"   Email: {person.email or 'Not available'}")
        print(f"   Phone: {person.phone or 'Not available'}")
        print(f"   Has Email: {person.has_email}")
        print(f"   Has Direct Phone: {person.has_direct_phone}")
        print(f"   Is Obfuscated: {person.is_obfuscated}")
        
        # Attempt to reveal contact details
        if person.apollo_person_id:
            print(f"   Attempting contact reveal for {person.first_name}...")
            revealed = client.reveal_contact(person)
            if revealed.email != person.email or revealed.phone != person.phone:
                print(f"   REVEALED Email: {revealed.email or 'Still not available'}")
                print(f"   REVEALED Phone: {revealed.phone or 'Still not available'}")
            else:
                print(f"   No additional contact info revealed")
        
        print()

if __name__ == "__main__":
    main()