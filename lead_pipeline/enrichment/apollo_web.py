"""Apollo.io web scraping for contact reveals when API credits are unavailable."""

from __future__ import annotations

import time
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from lead_pipeline.utils.logger import setup_logger

logger = setup_logger("enrichment.apollo_web")


@dataclass
class ApolloSession:
    """Manages Apollo web session for contact reveals."""
    
    session: requests.Session
    base_url: str = "https://app.apollo.io"
    
    def __post_init__(self):
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })


class ApolloWebScraper:
    """Web scraper for Apollo contact reveals when API reveals are unavailable."""
    
    def __init__(self, email: str = None, password: str = None):
        self.email = email
        self.password = password
        self.session = None
        self.logged_in = False
        
    def login(self) -> bool:
        """Login to Apollo web interface."""
        if not self.email or not self.password:
            logger.error("Apollo web credentials not provided")
            return False
            
        self.session = requests.Session()
        apollo_session = ApolloSession(self.session)
        
        try:
            # Get login page
            login_url = urljoin(apollo_session.base_url, "/login")
            response = self.session.get(login_url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find CSRF token
            csrf_token = None
            csrf_input = soup.find('input', {'name': 'authenticity_token'})
            if csrf_input:
                csrf_token = csrf_input.get('value')
            
            # Login payload
            login_data = {
                'user[email]': self.email,
                'user[password]': self.password,
                'commit': 'Sign In'
            }
            
            if csrf_token:
                login_data['authenticity_token'] = csrf_token
            
            # Submit login
            response = self.session.post(login_url, data=login_data, timeout=30)
            response.raise_for_status()
            
            # Check if login successful (redirect or dashboard content)
            if 'dashboard' in response.url or 'people' in response.url:
                self.logged_in = True
                logger.info("Successfully logged into Apollo web interface")
                return True
            else:
                logger.error("Apollo login failed - check credentials")
                return False
                
        except Exception as e:
            logger.error(f"Apollo login error: {e}")
            return False
    
    def reveal_contact(self, apollo_person_id: str) -> dict[str, str]:
        """Reveal contact details for a person via web interface."""
        if not self.logged_in:
            logger.warning("Not logged into Apollo - attempting login")
            if not self.login():
                return {"email": "", "phone": "", "error": "Login failed"}
        
        try:
            # Navigate to person profile page
            person_url = f"{self.session.headers.get('Referer', 'https://app.apollo.io')}/people/{apollo_person_id}"
            response = self.session.get(person_url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for reveal buttons and click them
            email = self._extract_email(soup, apollo_person_id)
            phone = self._extract_phone(soup, apollo_person_id)
            
            return {
                "email": email,
                "phone": phone,
                "error": ""
            }
            
        except Exception as e:
            logger.error(f"Contact reveal failed for {apollo_person_id}: {e}")
            return {"email": "", "phone": "", "error": str(e)}
    
    def _extract_email(self, soup: BeautifulSoup, person_id: str) -> str:
        """Extract email from person profile page."""
        # Look for email reveal button or displayed email
        email_selectors = [
            'button[data-cy="email-reveal"]',
            'button[data-testid="email-reveal"]', 
            'span[data-cy="email"]',
            'span[data-testid="email"]',
            '.email-field',
            '.contact-email'
        ]
        
        for selector in email_selectors:
            element = soup.select_one(selector)
            if element:
                # If it's a button, try to click it via AJAX
                if element.name == 'button':
                    return self._click_reveal_button(element, person_id, 'email')
                else:
                    # Extract email text
                    email_text = element.get_text(strip=True)
                    email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', email_text)
                    if email_match:
                        return email_match.group(0)
        
        # Fallback: search for email patterns in the entire page
        email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        emails = email_pattern.findall(soup.get_text())
        
        # Filter out common non-contact emails
        excluded_domains = ['apollo.io', 'example.com', 'test.com', 'domain.com']
        for email in emails:
            if not any(domain in email.lower() for domain in excluded_domains):
                return email
        
        return ""
    
    def _extract_phone(self, soup: BeautifulSoup, person_id: str) -> str:
        """Extract phone from person profile page."""
        # Look for phone reveal button or displayed phone
        phone_selectors = [
            'button[data-cy="phone-reveal"]',
            'button[data-testid="phone-reveal"]',
            'span[data-cy="phone"]', 
            'span[data-testid="phone"]',
            '.phone-field',
            '.contact-phone'
        ]
        
        for selector in phone_selectors:
            element = soup.select_one(selector)
            if element:
                # If it's a button, try to click it via AJAX
                if element.name == 'button':
                    return self._click_reveal_button(element, person_id, 'phone')
                else:
                    # Extract phone text
                    phone_text = element.get_text(strip=True)
                    phone_match = re.search(r'[\+]?[1-9]?[\-\.\s]?\(?[0-9]{3}\)?[\-\.\s]?[0-9]{3}[\-\.\s]?[0-9]{4}', phone_text)
                    if phone_match:
                        return phone_match.group(0)
        
        # Fallback: search for phone patterns in the entire page
        phone_pattern = re.compile(r'[\+]?[1-9]?[\-\.\s]?\(?[0-9]{3}\)?[\-\.\s]?[0-9]{3}[\-\.\s]?[0-9]{4}')
        phones = phone_pattern.findall(soup.get_text())
        
        for phone in phones:
            # Basic validation - should have at least 10 digits
            digits_only = re.sub(r'\D', '', phone)
            if len(digits_only) >= 10:
                return phone
        
        return ""
    
    def _click_reveal_button(self, button_element, person_id: str, contact_type: str) -> str:
        """Attempt to click reveal button via AJAX request."""
        try:
            # Look for data attributes that might contain reveal endpoint
            reveal_url = button_element.get('data-url') or button_element.get('data-href')
            if not reveal_url:
                # Construct likely reveal endpoint
                reveal_url = f"/api/v1/people/{person_id}/reveal_{contact_type}"
            
            # Make AJAX request to reveal contact
            headers = {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            response = self.session.post(reveal_url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get(contact_type, "")
            
        except Exception as e:
            logger.debug(f"AJAX reveal failed for {contact_type}: {e}")
        
        return ""
    
    def bulk_reveal_contacts(self, apollo_person_ids: list[str], delay_seconds: float = 1.0) -> dict[str, dict[str, str]]:
        """Reveal contacts for multiple people with rate limiting."""
        results = {}
        
        logger.info(f"Starting bulk reveal for {len(apollo_person_ids)} contacts")
        
        for i, person_id in enumerate(apollo_person_ids, 1):
            logger.info(f"Revealing contact {i}/{len(apollo_person_ids)}: {person_id}")
            
            result = self.reveal_contact(person_id)
            results[person_id] = result
            
            # Rate limiting
            if i < len(apollo_person_ids):
                time.sleep(delay_seconds)
        
        successful_reveals = sum(1 for r in results.values() if r.get('email') or r.get('phone'))
        logger.info(f"Successfully revealed {successful_reveals}/{len(apollo_person_ids)} contacts")
        
        return results