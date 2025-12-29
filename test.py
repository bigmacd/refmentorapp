

from datetime import datetime
import math


testDates = ['Thursday, September 4, 2025', 'Wednesday, September 17, 2025', 'Saturday, October 4, 2025', 'Thursday, October 16, 2025']
validIndices = [0, 3, 5, 7]


weekendDates = [
    ['Friday, September 5, 2025'],
    ['Friday, September 12, 2025', 'Saturday, September 13, 2025'],
    ['Friday, September 12, 2025', 'Saturday, September 13, 2025'],
    ['Friday, September 19, 2025', 'Saturday, September 20, 2025', 'Sunday, September 21, 2025'],
    ['Friday, September 26, 2025', 'Saturday, September 27, 2025'],
    ['Saturday, October 4, 2025'],
    ['Friday, October 10, 2025', 'Saturday, October 11, 2025'],
    ['Friday, October 17, 2025', 'Saturday, October 18, 2025', 'Sunday, October 19, 2025'],
    ['Friday, October 24, 2025', 'Saturday, October 25, 2025'],
    ['Saturday, November 1, 2025', 'Sunday, November 2, 2025'],
    ['Friday, November 7, 2025', 'Saturday, November 8, 2025', 'Sunday, November 9, 2025'],
    ['Friday, November 14, 2025', 'Saturday, November 15, 2025', 'Sunday, November 16, 2025'],
    ['Friday, November 21, 2025']
]


def findNextWeekendIndex(dates, currentDate) -> int:
    """
    Finds the closest date in the list that is after the current date.

    Args:
        date_strings (list[list[str]]): List of dates like 'Friday, September 5, 2025'

    Returns:
        list[str]: The closest future date strings, or None if none found.

        for index, weekend in enumerate(dates):
    """
    now = datetime.now()

    #now = datetime.strptime(currentDate, '%A, %B %d, %Y') # just for testing


    retVal = None
    distance = math.inf

    for index, weekend in enumerate(dates):
        for date in weekend:
            # Parse the date string
            dt = datetime.strptime(date, '%A, %B %d, %Y')
            if dt >= now:
                # found a date in the future, check how far away it is first and track the index
                if (dt - now).days < distance:
                    distance = (dt - now).days
                    retVal = index

    return retVal



for index, date in enumerate(testDates):
    result = findNextWeekendIndex(weekendDates, date)
    if result is not None:
        assert result == validIndices[index]
    else:
        print("could not find a weekend in-season that is in the future.")
