#!/usr/bin/env python3
"""Test contact reveal functionality with current Apollo API key."""

import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from lead_pipeline.utils.config import load_config
from lead_pipeline.enrichment.apollo import ApolloClient

def main():
    load_dotenv()
    config = load_config("config/config.yaml")
    client = ApolloClient(config)
    
    print("Testing contact reveal with your Apollo account...")
    
    # Get initial search results
    people = client.search_people()
    print(f"Found {len(people)} prospects")
    
    # Test reveal on first few candidates
    reveal_count = 0
    for i, person in enumerate(people[:5], 1):
        print(f"\n{i}. {person.display_name}")
        print(f"   Company: {person.organization_name}")
        print(f"   Title: {person.title}")
        print(f"   Initial Email: '{person.email}'")
        print(f"   Initial Phone: '{person.phone}'")
        print(f"   Has Email Flag: {person.has_email}")
        print(f"   Has Phone Flag: {person.has_direct_phone}")
        print(f"   Apollo ID: {person.apollo_person_id}")
        
        if person.apollo_person_id:
            print(f"   🔍 Attempting reveal...")
            try:
                revealed = client.reveal_contact(person)
                
                if revealed.email and revealed.email != person.email and "email_not_unlocked" not in revealed.email:
                    print(f"   ✅ REVEALED Email: {revealed.email}")
                    reveal_count += 1
                else:
                    print(f"   ❌ Email reveal failed or not available")
                
                if revealed.phone and revealed.phone != person.phone:
                    print(f"   ✅ REVEALED Phone: {revealed.phone}")
                else:
                    print(f"   ❌ Phone reveal failed or not available")
                    
            except Exception as e:
                print(f"   ❌ Reveal error: {e}")
    
    print(f"\n📊 Successfully revealed contact info for {reveal_count}/5 prospects")
    print(f"Your Apollo account {'HAS' if reveal_count > 0 else 'DOES NOT HAVE'} contact reveal credits")

if __name__ == "__main__":
    main()