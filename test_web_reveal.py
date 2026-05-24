#!/usr/bin/env python3
"""Test Apollo web scraping reveal functionality."""

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
    
    # Note: You'll need to add your Apollo web login credentials to config.yaml
    config = load_config("config/config.yaml")
    
    print("=== Apollo Web Scraping Contact Reveal Test ===")
    print(f"Web reveal enabled: {getattr(config.apollo, 'web_reveal_enabled', False)}")
    
    web_creds = getattr(config.apollo, 'web_credentials', {})
    has_credentials = bool(web_creds.get('email') and web_creds.get('password'))
    print(f"Web credentials configured: {has_credentials}")
    
    if not has_credentials:
        print("\n⚠️  To enable web scraping fallback:")
        print("1. Add your Apollo login email and password to config/config.yaml:")
        print("   apollo:")
        print("     web_credentials:")
        print("       email: 'your-apollo-email@example.com'")
        print("       password: 'your-apollo-password'")
        print("\n2. Make sure web_reveal_enabled: true")
        print("\n3. Re-run this test")
        return
    
    client = ApolloClient(config)
    
    # Get some prospects
    print("\nSearching for prospects...")
    people = client.search_people()
    print(f"Found {len(people)} prospects")
    
    if not people:
        print("No prospects found. Check your Apollo configuration.")
        return
    
    # Test contact reveal on first prospect
    test_person = people[0]
    print(f"\n🔍 Testing contact reveal for: {test_person.display_name}")
    print(f"   Company: {test_person.organization_name}")
    print(f"   Title: {test_person.title}")
    print(f"   Has Email Flag: {test_person.has_email}")
    print(f"   Has Phone Flag: {test_person.has_direct_phone}")
    print(f"   Apollo ID: {test_person.apollo_person_id}")
    
    # This will try API first, then fallback to web scraping
    revealed = client.reveal_contact(test_person)
    
    print(f"\n📧 Email Results:")
    print(f"   Before: '{test_person.email}'")
    print(f"   After:  '{revealed.email}'")
    
    print(f"\n📞 Phone Results:")
    print(f"   Before: '{test_person.phone}'")
    print(f"   After:  '{revealed.phone}'")
    
    if revealed.email != test_person.email or revealed.phone != test_person.phone:
        print("\n✅ SUCCESS: Contact reveal worked!")
        if revealed.email and revealed.email != test_person.email:
            print(f"   📧 Revealed email: {revealed.email}")
        if revealed.phone and revealed.phone != test_person.phone:
            print(f"   📞 Revealed phone: {revealed.phone}")
    else:
        print("\n❌ No new contact info revealed")
        print("   This could mean:")
        print("   • Contact info not available for this prospect")
        print("   • Web scraping couldn't find contact reveal buttons")
        print("   • Apollo account doesn't have web reveals")
        print("   • Web scraping needs adjustments for current Apollo UI")

if __name__ == "__main__":
    main()