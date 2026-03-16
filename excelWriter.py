import math
import xlsxwriter

""" This is the format of the data coming in:

Date: 2023-01-07 00:00:00
	Referee: Kareem Awad
	Position: Center
	Mentor: David Helfgott
	Comments: Kareem arrived at 8:45 for his 9:00 game. He was unsure of how to proceed, was not fully aware of how the build out lines worked. And was unaware of rules for heading at this age group. He was dressed professionally but did not have a coin. Kareem managed this U10 game fairly well. He moved well on the field.  He allowed substitutions on corner kicks and twice stopped play while ball was in possession of keeper to allow a substitute. Prior to second game we talked about better proximity to play on field and managing subs.  Both coaches were new and also did not know rules.

	Referee: Kareem Awad
	Position: Center
	Mentor: David Helfgott
	Comments: In Kareems second game he positioned himself better in field to see play and ball near touch lines. We talked at halftime about talking to players on field to clear up confusion about calls. Kareem did note that he felt more confident in second game. NOTE:  in first game, both keepers did not have pennies or jerseys to distinguish them from other players.

Date: 2023-01-14 00:00:00
	Referee: Kareem Awad
	Position: Center
	Mentor: David Helfgott
	Comments: Kareem arrived at 8:45 for his 9:00 game. He was unsure of how to proceed, was not fully aware of how the build out lines worked. And was unaware of rules for heading at this age group. He was dressed professionally but did not have a coin. Kareem managed this U10 game fairly well. He moved well on the field.  He allowed substitutions on corner kicks and twice stopped play while ball was in possession of keeper to allow a substitute. Prior to second game we talked about better proximity to play on field and managing subs.  Both coaches were new and also did not know rules.

	Referee: Kareem Awad
	Position: Center
	Mentor: David Helfgott
	Comments: In Kareems second game he positioned himself better in field to see play and ball near touch lines. We talked at halftime about talking to players on field to clear up confusion about calls. Kareem did note that he felt more confident in second game. NOTE:  in first game, both keepers did not have pennies or jerseys to distinguish them from other players.

...and so on

Spreadsheet is (this does not show the headers)
______________________________________________________________________________________________________________
|  Date           |  Referee  |  Position  |  Mentor  |  Comments                                            |
|_________________|___________|____________|__________|______________________________________________________|
|                 |  Referee  |  Position  |  Mentor  |  Comment                                             |
|_________________|___________|____________|__________|______________________________________________________|
"""

DATE_COLUMN = 0
REFEREE_COLUMN = 1
POSITION_COLUMN = 2
MENTOR_COLUMN = 3
COMMENTS_COLUMN = 4
GAMEID_COLUMN = 5
CENTER_COLUMN = 6
AR1_COLUMN = 7
AR2_COLUMN = 8
GAME_DATE_COLUMN = 9
VENUE_COLUMN = 10
TIME_COLUMN = 11
AGE_COLUMN = 12
LEVEL_COLUMN = 13

headers = [
            { 'text': "Date", 'size': 23.75 },
            { 'text': "Referee", 'size': 43.86 },
            { 'text': "Position", 'size':  9.29, },
            { 'text': "Mentor", 'size': 26.00 },
            { 'text': "Comments", 'size': 88.71 }
]

extraHeaders = [
    { 'text': "GameID", 'size': 12.29 },
    { 'text': "Center", 'size': 43.86 },
    { 'text': "AR1", 'size': 43.86 },
    { 'text': "AR2", 'size': 43.86 },
    { 'text': "Game Date", 'size': 23.75 },
    { 'text': "Venue", 'size': 26.00 },
    { 'text': "Time", 'size': 15.29 },
    { 'text': "Age", 'size': 10.29 },
    { 'text': "Level", 'size': 15.29 }
]

def writeDate(worksheet: xlsxwriter.worksheet.Worksheet,
              headerFormat: xlsxwriter.format.Format,
              format: xlsxwriter.format.Format,
              lineNumber: int,
              line: str) -> None:
    """
    If this is the first line, write the header.  Then write the date.

    Args:
        worksheet (_type_): _description_
        lineNumber (int): _description_
        columnNumber (int): _description_
        line (str): _description_
    """
    if lineNumber == 0:
        addHeaders(worksheet, headerFormat)
        lineNumber += 1

    worksheet.write(lineNumber, DATE_COLUMN, line, format)
    return lineNumber


def addHeaders(worksheet: xlsxwriter.worksheet.Worksheet,
               format: xlsxwriter.format.Format) -> None:
    for i, header in enumerate(headers + extraHeaders):
        worksheet.set_column(i, i, header['size'])
        worksheet.write(0, i, header['text'], format)


def writeReferee(worksheet: xlsxwriter.worksheet.Worksheet,
                 format: xlsxwriter.format.Format,
                 lineNumber: int,
                 line: str) -> None:
    worksheet.write(lineNumber, REFEREE_COLUMN, line, format)



def writePosition(worksheet: xlsxwriter.worksheet.Worksheet,
                  format: xlsxwriter.format.Format,
                  lineNumber: int,
                  line: str) -> None:
    worksheet.write(lineNumber, POSITION_COLUMN, line, format)


def writeMentor(worksheet: xlsxwriter.worksheet.Worksheet,
                format: xlsxwriter.format.Format,
                lineNumber: int,
                line: str) -> None:
    worksheet.write(lineNumber, MENTOR_COLUMN, line, format)


def _comment_display_lines(text: str, column_width: float = 88.71, chars_per_line: float = None) -> int:
    """Estimate how many display lines wrapped text will need. Uses column_width (char units)."""
    if chars_per_line is None:
        chars_per_line = max(20, column_width - 3)  # leave a small margin
    lines = 0
    for part in text.split('\n'):
        part = part.strip()
        if part:
            lines += max(1, math.ceil(len(part) / chars_per_line))
        else:
            lines += 1
    return max(1, lines)


def writeComments(worksheet: xlsxwriter.worksheet.Worksheet,
                  format: xlsxwriter.format.Format,
                  lineNumber: int,
                  line: str) -> None:
    worksheet.write(lineNumber, COMMENTS_COLUMN, line, format)
    # Set row height so wrapped text isn't compacted (xlsxwriter has no autofit row height)
    num_lines = _comment_display_lines(line)
    row_height = 15 * num_lines  # 15 = default single-line height in character units
    worksheet.set_row(lineNumber, row_height)


def writeGameID(worksheet: xlsxwriter.worksheet.Worksheet,
                 format: xlsxwriter.format.Format,
                 lineNumber: int,
                 line: str) -> None:
    worksheet.write(lineNumber, GAMEID_COLUMN, line, format)


def writeCenter(worksheet: xlsxwriter.worksheet.Worksheet,
                format: xlsxwriter.format.Format,
                lineNumber: int,
                line: str) -> None:
    worksheet.write(lineNumber, CENTER_COLUMN, line, format)


def writeAR1(worksheet: xlsxwriter.worksheet.Worksheet,
             format: xlsxwriter.format.Format,
             lineNumber: int,
             line: str) -> None:
    worksheet.write(lineNumber, AR1_COLUMN, line, format)


def writeAR2(worksheet: xlsxwriter.worksheet.Worksheet,
             format: xlsxwriter.format.Format,
             lineNumber: int,
             line: str) -> None:
    worksheet.write(lineNumber, AR2_COLUMN, line, format)


def writeGameDate(worksheet: xlsxwriter.worksheet.Worksheet,
                   format: xlsxwriter.format.Format,
                   lineNumber: int,
                   line: str) -> None:
    worksheet.write(lineNumber, GAME_DATE_COLUMN, line, format)


def writeVenue(worksheet: xlsxwriter.worksheet.Worksheet,
               format: xlsxwriter.format.Format,
               lineNumber: int,
               line: str) -> None:
    worksheet.write(lineNumber, VENUE_COLUMN, line, format)


def writeTime(worksheet: xlsxwriter.worksheet.Worksheet,
              format: xlsxwriter.format.Format,
              lineNumber: int,
              line: str) -> None:
    worksheet.write(lineNumber, TIME_COLUMN, line, format)


def writeAge(worksheet: xlsxwriter.worksheet.Worksheet,
              format: xlsxwriter.format.Format,
              lineNumber: int,
              line: str) -> None:
    worksheet.write(lineNumber, AGE_COLUMN, line, format)


def writeLevel(worksheet: xlsxwriter.worksheet.Worksheet,
               format: xlsxwriter.format.Format,
               lineNumber: int,
               line: str) -> None:
    worksheet.write(lineNumber, LEVEL_COLUMN, line, format)


def cleanLine(line: str) -> str:
    line = line.lstrip()
    line = line.rstrip()
    line = line.strip('\t')
    return line

def getExcelFromText(data: str) -> None:

    workbook = xlsxwriter.Workbook("report.xlsx")


    # TO DO add wrap and centering if needed for both header and normal

    header_cell = workbook.add_format()
    header_cell.set_pattern(1)
    header_cell.set_bold()
    header_cell.set_font_size(12)
    header_cell.set_font_name('Arial')
    header_cell.set_border(1)
    header_cell.set_bg_color("silver")

    normal_cell = workbook.add_format()
    normal_cell.set_font_size(12)
    normal_cell.set_font_name('Arial')
    normal_cell.set_border(1)
    normal_cell.set_bg_color("silver")
    normal_cell.set_text_wrap(True)
    normal_cell.set_align('vjustify')

    worksheet = workbook.add_worksheet("report")
    worksheet.set_column(COMMENTS_COLUMN, COMMENTS_COLUMN, 88.71, normal_cell)

    """
    1. write a line with date in first cell
    2. after writing the data, write a line with headers of
       a. Referee
       b. Position
       c. Mentor
       d. Comment

    if gameid exists, then the headers also include:
       e. gameid
       f. center
       g. ar1
       h. ar2
       i. game_date
       j. venue
       k. time
       l. age
       m. level


    3. write the data for the above headers on the next line
    """

    # Line prefixes that start a new field (used to know when a multi-line comment ends)
    KNOWN_PREFIXES = (
        'Date:', 'Referee:', 'Position:', 'Mentor:', 'Comments:',
        'Game ID:', 'Center:', 'AR1:', 'AR2:', 'Game Date:', 'Venue:', 'Time:', 'Age Group:', 'Level:'
    )

    lineNumber = 0
    lines = data.split('\n')
    i = 0
    while i < len(lines):
        line = cleanLine(lines[i])

        if line.startswith('Date:'):
            lineNumber = writeDate(worksheet, header_cell, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith('Referee:'):
            writeReferee(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith("Position:"):
            writePosition(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith('Mentor:'):
            writeMentor(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith('Comments:'):
            # Gather this line's text after "Comments:" and any following lines that are not a known header
            comment_parts = [line.split(':', 1)[1].strip()]
            i += 1
            while i < len(lines):
                next_line = cleanLine(lines[i])
                if any(next_line.startswith(prefix) for prefix in KNOWN_PREFIXES):
                    break
                comment_parts.append(next_line)
                i += 1
            full_comment = '\n'.join(comment_parts)
            writeComments(worksheet, normal_cell, lineNumber, full_comment)
            lineNumber += 1
            # Do not increment i here; the next line (that broke the loop) will be processed on next iteration

        elif line.startswith('Game ID:'):
            writeGameID(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith('Center:'):
            writeCenter(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith('AR1:'):
            writeAR1(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith('AR2:'):
            writeAR2(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith('Game Date:'):
            writeGameDate(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith('Venue:'):
            writeVenue(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith('Time:'):
            writeTime(worksheet, normal_cell, lineNumber, line.split(':', 1)[1])
            i += 1

        elif line.startswith('Age Group:'):
            writeAge(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        elif line.startswith('Level:'):
            writeLevel(worksheet, normal_cell, lineNumber, line.split(':')[1])
            i += 1

        else:
            i += 1

    workbook.close()


if __name__ == "__main__":
    data = """
    Date: 2023-01-07 00:00:00
	Referee: Kareem Awad
	Position: Center
	Mentor: David Helfgott
	Comments: Kareem arrived at 8:45 for his 9:00 game. He was unsure of how to proceed, was not fully aware of how the build out lines worked. And was unaware of rules for heading at this age group. He was dressed professionally but did not have a coin. Kareem managed this U10 game fairly well. He moved well on the field.  He allowed substitutions on corner kicks and twice stopped play while ball was in possession of keeper to allow a substitute. Prior to second game we talked about better proximity to play on field and managing subs.  Both coaches were new and also did not know rules.

	Referee: Kareem Awad
	Position: Center
	Mentor: David Helfgott
	Comments: In Kareems second game he positioned himself better in field to see play and ball near touch lines. We talked at halftime about talking to players on field to clear up confusion about calls. Kareem did note that he felt more confident in second game. NOTE:  in first game, both keepers did not have pennies or jerseys to distinguish them from other players.

    Date: 2023-01-14 00:00:00
	Referee: Kareem Awad
	Position: Center
	Mentor: David Helfgott
	Comments: Kareem arrived at 8:45 for his 9:00 game. He was unsure of how to proceed, was not fully aware of how the build out lines worked. And was unaware of rules for heading at this age group. He was dressed professionally but did not have a coin. Kareem managed this U10 game fairly well. He moved well on the field.  He allowed substitutions on corner kicks and twice stopped play while ball was in possession of keeper to allow a substitute. Prior to second game we talked about better proximity to play on field and managing subs.  Both coaches were new and also did not know rules.

	Referee: Kareem Awad
	Position: Center
	Mentor: David Helfgott
	Comments: In Kareems second game he positioned himself better in field to see play and ball near touch lines. We talked at halftime about talking to players on field to clear up confusion about calls. Kareem did note that he felt more confident in second game. NOTE:  in first game, both keepers did not have pennies or jerseys to distinguish them from other players.
"""

    getExcelFromText(data)
