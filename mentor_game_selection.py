#!/usr/bin/env python3
"""
Mentor Game Selection Component
Allows mentors to select games they want to mentor
"""

from collections import defaultdict
from datetime import datetime, timedelta
import logging
from nicegui import ui


class MentorGameSelection:
    """Component for mentors to select games they want to mentor"""

    def __init__(self, db, auth_manager, all_match_data, dates, logger=None):
        """
        Initialize the mentor game selection component

        Args:
            db: Database connection object
            auth_manager: Authentication manager instance
            all_match_data: Dictionary of match data organized by date -> venue -> games
            dates: List of date strings
            logger: Optional logger instance
        """
        self.db = db
        self.auth_manager = auth_manager
        self.all_match_data = all_match_data
        self.dates = dates
        self.logger = logger or logging.getLogger(__name__)
        self.current_user = None
        self.current_mentor_name = None

    def _get_weekend_dates(self):
        """Filter dates to show only Friday, Saturday, Sunday"""
        weekend_dates = []
        for date_str in self.dates:
            if date_str.startswith(('Friday', 'Saturday', 'Sunday')):
                weekend_dates.append(date_str)
        return weekend_dates

    def _get_game_selections_for_date(self, date_str):
        """Get all mentor selections for a specific date"""
        selections = self.db.getMentorGameSelections(game_date=date_str)
        # Organize by venue -> game_id -> list of mentors
        selections_dict = {}
        for sel in selections:
            venue = sel['venue']
            game_id = sel['game_id']
            if venue not in selections_dict:
                selections_dict[venue] = {}
            if game_id not in selections_dict[venue]:
                selections_dict[venue][game_id] = []
            selections_dict[venue][game_id].append(sel['mentor_name'])
        return selections_dict

    def _parse_mentor_name(self, mentor_str):
        """Parse mentor string 'Firstname Lastname' into firstname, lastname"""
        parts = mentor_str.split()
        if len(parts) >= 2:
            return parts[0].lower(), parts[1].lower()
        return None, None

    def _toggle_game_selection(self, mentor_name, game_date, venue, game_id, is_checked, selected_by_label, checkbox_ref=None):
        """Toggle selection of a game for a mentor"""
        firstname, lastname = self._parse_mentor_name(mentor_name)
        if not firstname or not lastname:
            ui.notify('Invalid mentor name', type='negative')
            return

        if is_checked:
            # Add selection
            success, message = self.db.addMentorGameSelection(
                firstname, lastname, game_date, venue, game_id
            )
            if success:
                ui.notify(message, type='positive')
            else:
                ui.notify(message, type='warning')
        else:
            # Remove selection
            success, message = self.db.removeMentorGameSelection(
                firstname, lastname, game_date, venue, game_id
            )
            if success:
                ui.notify(message, type='positive')
            else:
                ui.notify(message, type='warning')

        # Update the "Selected by" display
        selected_mentors = self.db.getGameSelectionsByGame(game_date, venue, game_id)
        if selected_mentors:
            selected_by_label.text = 'Selected by: ' + ', '.join(selected_mentors)
            selected_by_label.classes('text-xs text-green-600')
        else:
            selected_by_label.text = 'Not selected'
            selected_by_label.classes('text-xs text-gray-400')

        # Update checkbox disabled state based on whether other mentors have selected
        if checkbox_ref is not None:
            checkbox_disabled = bool(selected_mentors) and (mentor_name not in selected_mentors)
            if checkbox_disabled:
                checkbox_ref.props('disable')
                checkbox_ref.tooltip('Another mentor has already selected this game')
            else:
                checkbox_ref.props(remove='disable')
                checkbox_ref.tooltip(None)


    def _render_day_section(self, date_str, games_by_venue):
        """Render games for a specific day"""
        selections = self._get_game_selections_for_date(date_str)

        with ui.expansion(date_str, icon='event').classes('w-full mb-4'):
            # Get venues for this date
            venues = sorted(games_by_venue.keys())

            for venue in venues:
                with ui.expansion(venue, icon='place').classes('w-full mb-2'):
                    games = games_by_venue[venue]

                    # Render games as cards for better UX
                    for game in games:
                            game_id = game.get('GameID', '')
                            selected_mentors = selections.get(venue, {}).get(game_id, [])
                            is_selected = self.current_mentor_name and self.current_mentor_name in selected_mentors

                            with ui.card().classes('w-full mb-2 p-3 border border-gray-200'):
                                with ui.row().classes('w-full items-start gap-4'):
                                    # Left column: Time and game info
                                    with ui.column().classes('flex-1 gap-1'):
                                        ui.label(f"⏰ {game.get('Time', '')}").classes('font-semibold text-lg')
                                        ui.label(f"📋 {game.get('Level', '')} - {game.get('Age', '')}").classes('text-sm text-gray-600')

                                    # Middle column: Referees
                                    with ui.column().classes('flex-1 gap-1'):
                                        ui.label('Referees:').classes('font-semibold text-sm')
                                        ui.label(f"Center: {game.get('Center', 'None')}").classes('text-sm')
                                        ui.label(f"AR1: {game.get('AR1', 'None')}").classes('text-sm')
                                        ui.label(f"AR2: {game.get('AR2', 'None')}").classes('text-sm')

                                    # Right column: Selection and selected by info
                                    with ui.column().classes('flex-1 gap-2 items-end'):
                                        # Selected by info (create label first so we can update it)
                                        selected_by_label = ui.label('')

                                        # Update label with current selections
                                        if selected_mentors:
                                            selected_by_label.text = 'Selected by: ' + ', '.join(selected_mentors)
                                            selected_by_label.classes('text-xs text-green-600')
                                        else:
                                            selected_by_label.text = 'Not selected'
                                            selected_by_label.classes('text-xs text-gray-400')

                                        # Selection checkbox
                                        if self.current_mentor_name:
                                            # Disable checkbox if other mentors have selected this game
                                            # But allow current mentor to toggle their own selection
                                            checkbox_disabled = bool(selected_mentors) and (self.current_mentor_name not in selected_mentors)

                                            # Create a mutable container to hold checkbox reference for the closure
                                            checkbox_container = {'ref': None}

                                            # Create the handler that will use the checkbox reference from container
                                            def make_handler(mentor, date, ven, gid, label, container):
                                                def handler(event):
                                                    # event.value contains the new checkbox state
                                                    checkbox_ref = container['ref']
                                                    self._toggle_game_selection(mentor, date, ven, gid, event.value, label, checkbox_ref)
                                                return handler

                                            handler = make_handler(
                                                self.current_mentor_name,
                                                date_str,
                                                venue,
                                                game_id,
                                                selected_by_label,
                                                checkbox_container
                                            )

                                            # Create checkbox with handler passed during initialization
                                            checkbox = ui.checkbox(
                                                'I will mentor this game',
                                                value=is_selected,
                                                on_change=handler
                                            ).classes('flex-shrink-0')

                                            # Store checkbox reference in container for the handler to use
                                            checkbox_container['ref'] = checkbox

                                            if checkbox_disabled:
                                                checkbox.props('disable')
                                                checkbox.tooltip('Another mentor has already selected this game')
                                        else:
                                            # If no mentor selected, just show who has selected it
                                            if selected_mentors:
                                                ui.label('Selected by:').classes('text-xs text-gray-500 font-semibold')
                                                for mentor in selected_mentors:
                                                    ui.label(f"✓ {mentor}").classes('text-xs text-green-600')
                                            else:
                                                ui.label('Not selected').classes('text-xs text-gray-400')


    def _organizeDatesIntoWeekends(self, dates: list) -> list:
        """Organize a list of date strings into weekends (Fri/Sat/Sun groups)"""

        fmt = '%A, %B %-d, %Y'

        # parse and sort
        dt_list = sorted(datetime.strptime(d, fmt) for d in dates)

        groups = defaultdict(list)

        for dt in dt_list:
            # weekday(): Monday=0 ... Sunday=6
            wd = dt.weekday()
            if wd in (4, 5, 6):  # Fri/Sat/Sun
                friday = dt - timedelta(days=wd - 4)  # normalize to that weekend's Friday
                key = friday.date()
                groups[key].append(dt)

        # if you want them back as strings, ordered by weekend:
        weekends = []
        for weekend_start in sorted(groups):
            weekend_dates = [d.strftime(fmt) for d in sorted(groups[weekend_start])]
            weekends.append(weekend_dates)

        return weekends


    def render(self):
        """Render the mentor game selection interface"""
        # Get current user and determine mentor name
        self.current_user = self.auth_manager.get_current_user()

        # Get mentors list
        mentors = self.db.getMentors()
        mentor_values = sorted([f'{m[0].capitalize()} {m[1].capitalize()}' for m in mentors])

        # Filter to current user if not admin
        filtered = [v for v in mentor_values if v.lower().startswith(self.current_user.lower())]
        if filtered:
            mentor_values = filtered

        self.current_mentor_name = mentor_values[0] if mentor_values else None

        with ui.card().classes('form-container w-full'):
            ui.label('Select Games to Mentor').classes('text-xl font-bold mb-4')
            ui.label(f'Mentor: {self.current_mentor_name}').classes('mb-4 font-semibold')

            # Check if data is loaded
            if not self.all_match_data:
                with ui.column().classes('items-center justify-center p-8'):
                    ui.spinner(size='lg')
                    ui.label('Loading game data...').classes('mt-4 text-gray-600')
                return

            # Get weekend dates
            weekend_dates = self._get_weekend_dates()
            weekend_dates = self._organizeDatesIntoWeekends(weekend_dates)

            # weekend_dates is a list of lists of date strings
            # each list is a weekend
            # each date string is in the format 'Friday, December 20, 2025'
            # we need to get the three dates from all_match_data that are closest to the current date

            # Get the three dates from weekend_dates that are closest to (and after) the current date
            current_date = datetime.now().date()

            # Parse all dates and calculate their distance from current_date
            def date_distance(date_str):
                """Calculate absolute days difference from current date"""
                parsed_date = datetime.strptime(date_str, '%A, %B %d, %Y').date()
                return abs((parsed_date - current_date).days)

            # Sort by distance and take the 3 closest dates
            thisWeekendDates = sorted(
                self.all_match_data.keys(),
                key=date_distance
            )[:3]

            # print(f"thisWeekendDates: {thisWeekendDates}")
            # thisWeekendDates: ['Friday, January 9, 2026', 'Saturday, January 10, 2026', 'Friday, January 16, 2026']

            if not thisWeekendDates:
                ui.label('No weekend games found.').classes('text-gray-500 mt-4')
                return

            # Group dates by day of week
            # friday_dates = [d for d in weekend_dates if d.startswith('Friday')]
            # saturday_dates = [d for d in weekend_dates if d.startswith('Saturday')]
            # sunday_dates = [d for d in weekend_dates if d.startswith('Sunday')]

            for date in thisWeekendDates:
                ui.label(f'{date[0]}').classes('text-lg font-bold mt-4 mb-2')
                self._render_day_section(date, self.all_match_data[date])


