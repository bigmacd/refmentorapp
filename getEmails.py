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
    bademails = [
        os.environ.get('badmentor1'),
        os.environ.get('badmentor2'),
        os.environ.get('badmentor3')
    ]

    emails = retrieveEmails()
    emails = sorted(emails)
    print(f"Retrieved {len(emails)} email addresses from MSL")

    # dedup the list
    uniqueEmails = list(set(emails))
    print(f"Deduped { len(emails) - len(uniqueEmails) } email addresses")

    for email in uniqueEmails:
        if email in bademails:
            continue
        print(email)

if __name__ == "__main__":
    main()
