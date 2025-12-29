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

headers = [
            { 'text': "Date", 'size': 23.75 },
            { 'text': "Referee", 'size': 43.86 },
            { 'text': "Position", 'size':  9.29, },
            { 'text': "Mentor", 'size': 26.00 },
            { 'text': "Comments", 'size': 88.71 }
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
    for i, header in enumerate(headers):
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


def writeComments(worksheet: xlsxwriter.worksheet.Worksheet,
                  format: xlsxwriter.format.Format,
                  lineNumber: int,
                  line: str) -> None:
    worksheet.write(lineNumber, COMMENTS_COLUMN, line, format)


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
    3. write the data for the four above headers on the next line
    """

    lineNumber = 0

    lines = data.split('\n')
    for line in lines:

        line = cleanLine(line)

        if line.startswith('Date:'):
            lineNumber = writeDate(worksheet, header_cell, normal_cell, lineNumber, line.split(':')[1])

        elif line.startswith('Referee:'):
            writeReferee(worksheet, normal_cell, lineNumber, line.split(':')[1])

        elif line.startswith("Position:"):
            writePosition(worksheet, normal_cell, lineNumber, line.split(':')[1])

        elif line.startswith('Mentor:'):
            writeMentor(worksheet, normal_cell, lineNumber, line.split(':')[1])

        elif line.startswith('Comments:'):
            writeComments(worksheet, normal_cell, lineNumber, line.split(':',1)[1])
            lineNumber += 1

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
