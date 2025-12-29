import datetime
import logging


# refmentoring-530@psyched-runner-378322.iam.gserviceaccount.com
credFile = 'psyched-runner-378322-6ea04e89b69e.json'


import gspread
from oauth2client.service_account import ServiceAccountCredentials


scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive'
]


def _toLower(name: str) -> str:
    return name.lower()


def _isLastSixMonths(certDate: datetime.datetime, now: datetime.datetime) -> bool:

    earliestData = now - datetime.timedelta(182)
    return earliestData <= certDate <= now


def adjustPerUSSF(certDate: datetime.datetime) -> int:
    year = certDate.year
    if certDate.month >= 7:  # certifcations after July 1 are for the next year
        year += 1
    return year


def _getThisYearsNewRefs(allRefs: list) -> list:
    now = datetime.datetime.now()
    retVal = []

    for ref in allRefs:
        try:
            certDate = datetime.datetime.strptime(ref[1], '%m/%d/%Y')
            if _isLastSixMonths(certDate, now):
                year = adjustPerUSSF(certDate)
                try:
                    l, f = ref[0].split(',')
                except Exception:
                    logging.warning(f"Error processing {ref[0]} from spreadsheet")
                    continue
                retVal.append((l.strip(), f.strip(), year))
        except Exception as ex:
            logging.warning(f"Top Level Error processing {ref[0]} from spreadsheet")
    return retVal


def getRefsFromGoogleSignupSheet() -> list:

    creds = ServiceAccountCredentials.from_json_keyfile_name(credFile)
    client = gspread.authorize(creds)

    spreadsheet = client.open('Referee Certification and Eligibility (Responses)')
    worksheet = spreadsheet.worksheet('Form Responses 1')

    names = worksheet.col_values(4)
    names.pop(0) # the column headers
    names = list(map(_toLower, names))

    years = worksheet.col_values(11)
    years.pop(0)


    return _getThisYearsNewRefs(list(zip(names, years)))


# x = getRefsFromGoogleSignupSheet()
# print(x)
