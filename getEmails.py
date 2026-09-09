from collections import Counter
import os
import mechanicalsoup

from refWebSites import MySoccerLeague


def retrieveEmails():
    br = mechanicalsoup.StatefulBrowser(soup_config={ 'features': 'lxml'})
    br.addheaders = [('User-agent', 'Chrome')]
    site = MySoccerLeague(br)
    _ = site.getAllReferees()
    return site.emails


def main():
    excludedEmails = os.environ.get('excludedEmails', '').split(',')
    excludeEmails = [email.strip() for email in excludedEmails]
    emails = retrieveEmails()
    emails = sorted(emails)
    print(f"Retrieved {len(emails)} email addresses from MSL")

    counts = Counter(emails)
    dups = {email: count for email, count in counts.items() if count > 1}
    for k, v in dups.items():
        print(f"Duplicate email: {k} appears {v} times")

    # dedup the list
    uniqueEmails = list(set(emails))
    print(f"Deduped { len(emails) - len(uniqueEmails) } email addresses")

    for email in uniqueEmails:
        if email in excludeEmails:
            continue
        print(email)

if __name__ == "__main__":
    main()
