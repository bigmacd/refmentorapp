#!/usr/bin/env python3
"""
Mentor Game Selection Component
Allows mentors to select games they want to mentor
"""

from collections import defaultdict
from datetime import datetime, timedelta
import logging
from typing import Callable, Optional, Tuple, Any
from nicegui import ui

from generateWorkload import name_is_new_ref, position_status_text, referee_experience_text


class MentorGameSelection:
    """Component for mentors to select games they want to mentor"""

    def __init__(self, db, auth_manager, all_match_data, dates, logger=None,
                 get_match_data: Optional[Callable[[], Tuple[Any, list]]] = None,
                 ensure_match_data: Optional[Callable[[], None]] = None,
                 ensure_workload: Optional[Callable[[], None]] = None):
        """
        Initialize the mentor game selection component

        Args:
            db: Database connection object
            auth_manager: Authentication manager instance
            all_match_data: Dictionary of match data organized by date -> venue -> games
            dates: List of date strings
            logger: Optional logger instance
            get_match_data: Optional callable that returns (all_match_data, dates) for polling when data is not yet loaded
        """
        self.db = db
        self.auth_manager = auth_manager
        self.all_match_data = all_match_data
        self.dates = dates
        self.get_match_data = get_match_data
        self.ensure_match_data = ensure_match_data
        self.ensure_workload = ensure_workload
        self.logger = logger or logging.getLogger(__name__)
        self.current_mentor_name = None

    def _current_org_id(self) -> int:
        org_id = self.auth_manager.get_current_organization_id()
        if org_id is not None:
            return org_id
        return self.db.getDefaultOrganizationId()

    def _get_weekend_dates(self):
        """Filter dates to show only Friday, Saturday, Sunday"""
        weekend_dates = []
        for date_str in self.dates:
            if date_str.startswith(('Friday', 'Saturday', 'Sunday')):
                weekend_dates.append(date_str)
        return weekend_dates

    def _get_game_selections_for_date(self, date_str):
        """Get all mentor selections for a specific date"""
        selections = self.db.getMentorGameSelections(game_date=date_str, organization_id=self._current_org_id())
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

    def _toggle_game_selection(self, mentor_name, game_date, venue, game_id, is_checked, selected_by_label, checkbox_ref=None, checkbox_container=None):
        """Toggle selection of a game for a mentor"""
        firstname, lastname = self._parse_mentor_name(mentor_name)
        if not firstname or not lastname:
            ui.notify('Invalid mentor name', type='negative')
            return

        org_id = self._current_org_id()
        if is_checked:
            # Add selection
            success, message = self.db.addMentorGameSelection(
                firstname, lastname, game_date, venue, game_id, org_id
            )
            if success:
                ui.notify(message, type='positive')
            else:
                ui.notify(message, type='warning')
                if checkbox_ref is not None:
                    if checkbox_container is not None:
                        checkbox_container['syncing'] = True
                    try:
                        checkbox_ref.value = False
                    finally:
                        if checkbox_container is not None:
                            checkbox_container['syncing'] = False
        else:
            # Remove selection
            success, message = self.db.removeMentorGameSelection(
                firstname, lastname, game_date, venue, game_id, org_id
            )
            if success:
                ui.notify(message, type='positive')
            else:
                ui.notify(message, type='warning')

        # Update the "Selected by" display
        selected_mentors = self.db.getGameSelectionsByGame(game_date, venue, game_id, org_id)
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


    def _render_ref_line(self, position: str, name: str, already_mentored: bool,
                         needs_followup: bool, is_new_ref: bool, *, as_ar: bool = False) -> None:
        has_name = bool(name) and name.strip().lower() != 'none'
        # "Already mentored" is only meaningful for new referees; follow-up can apply to anyone.
        note = position_status_text(
            already_mentored and is_new_ref,
            needs_followup,
            as_ar=as_ar,
        )
        with ui.row().classes('items-baseline gap-x-2 flex-wrap'):
            name_classes = 'text-sm font-semibold' if is_new_ref and has_name else 'text-sm'
            ui.label(f"{position}: {name or 'None'}").classes(name_classes)
            if has_name:
                identity_color = 'text-green-700 font-semibold' if is_new_ref else 'text-gray-500 italic'
                ui.label(referee_experience_text(is_new_ref)).classes(f'text-xs {identity_color}')
            if note:
                color = 'text-amber-700' if needs_followup else 'text-gray-500'
                ui.label(note).classes(f'text-xs italic {color}')


    def _render_day_section(self, date_str, games_by_venue):
        """Render games for a specific day"""

        # only use selections from games_by_venue if that game is in the data
        # from the run (ui.resultsFromRun)

        selections = self._get_game_selections_for_date(date_str)

        with ui.expansion(date_str, icon='event', value=True).classes('w-full mb-4'):
            # Get venues for this date
            venues = sorted(games_by_venue.keys())

            for venue in venues:
                with ui.expansion(venue, icon='place', value=True).classes('w-full mb-2'):
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
                                        self._render_ref_line(
                                            'Center', game.get('Center', 'None'),
                                            game.get('already_mentored_center', False),
                                            game.get('needs_followup_center', False),
                                            game.get('new_ref_center', False),
                                        )
                                        self._render_ref_line(
                                            'AR1', game.get('AR1', 'None'),
                                            game.get('already_mentored_ar1', False),
                                            game.get('needs_followup_ar1', False),
                                            game.get('new_ref_ar1', False),
                                            as_ar=True,
                                        )
                                        self._render_ref_line(
                                            'AR2', game.get('AR2', 'None'),
                                            game.get('already_mentored_ar2', False),
                                            game.get('needs_followup_ar2', False),
                                            game.get('new_ref_ar2', False),
                                            as_ar=True,
                                        )

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
                                                    if container.get('syncing'):
                                                        return
                                                    checkbox_ref = container['ref']
                                                    self._toggle_game_selection(
                                                        mentor, date, ven, gid, event.value, label, checkbox_ref, container
                                                    )
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
        try:
            dt_list = sorted(datetime.strptime(d, fmt) for d in dates)
        except Exception as e:
            self.logger.error(f"Error organizing dates into weekends: {e}")
            return []

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


    def _ensure_workload_for_org(self):
        cached_org = getattr(ui, 'resultsFromRunOrgId', None)
        if cached_org != self._current_org_id() and self.ensure_workload:
            try:
                self.ensure_workload()
            except Exception as e:
                self.logger.debug('ensure_workload failed: %s', e)

    def _ensure_match_data_loaded(self):
        if self.all_match_data is not None:
            return
        if self.ensure_match_data:
            try:
                self.ensure_match_data()
            except Exception as e:
                self.logger.debug('ensure_match_data failed: %s', e)
        if self.get_match_data:
            data, dates = self.get_match_data()
            self.all_match_data = data
            self.dates = dates or (list(data.keys()) if data else [])

    def render(self):
        """Render the mentor game selection interface"""
        self._ensure_workload_for_org()
        # Identify the logged-in mentor by user id / full name, not username prefix
        self.current_mentor_name = self.auth_manager.get_current_mentor_display_name()
        if not self.current_mentor_name:
            mentors = self.db.getMentors(self._current_org_id())
            mentor_values = sorted([f'{m[0].capitalize()} {m[1].capitalize()}' for m in mentors])
            self.current_mentor_name = mentor_values[0] if mentor_values else None

        card = ui.card().classes('form-container w-full')
        with card:
            ui.label('Select Games to Mentor').classes('text-xl font-bold mb-4')
            ui.label(f'Mentor: {self.current_mentor_name}').classes('mb-2 font-semibold')
            ui.label(
                'Only games with new referees are listed. Each crew member is labeled '
                'new or experienced so the mentoring focus is clear.'
            ).classes('text-sm text-gray-600 mb-4')

            # Check if data is loaded into memory (disk cache may exist before load_data runs)
            if self.all_match_data is None:
                with ui.column().classes('items-center justify-center p-8'):
                    ui.spinner(size='lg')
                    ui.label('Loading game data...').classes('mt-4 text-gray-600')
                    ui.label('Checking every few seconds. Data will appear when ready.').classes('text-sm text-gray-500 mt-2')

                def check_match_data_loaded():
                    self._ensure_match_data_loaded()
                    if self.all_match_data is not None:
                        card.clear()
                        with card:
                            ui.label('Select Games to Mentor').classes('text-xl font-bold mb-4')
                            ui.label(f'Mentor: {self.current_mentor_name}').classes('mb-2 font-semibold')
                            ui.label(
                                'Only games with new referees are listed. Each crew member is labeled '
                                'new or experienced so the mentoring focus is clear.'
                            ).classes('text-sm text-gray-600 mb-4')
                            self._render_content_after_header()
                    else:
                        ui.timer(0.5, check_match_data_loaded, once=True)

                ui.timer(0.5, check_match_data_loaded, once=True)
                return

            if not self.all_match_data:
                ui.label('No games are scheduled for this organization yet.').classes('text-gray-500 mt-4')
                return

            self._render_content_after_header()

    def _render_content_after_header(self):
        """Render weekend dates, extractNewRefRecords, and game sections. Caller provides card context."""
        # Get weekend dates
        weekend_dates = self._get_weekend_dates()
        weekend_dates = self._organizeDatesIntoWeekends(weekend_dates)
        # weekend_dates example:
        # [
        #   ['Friday, January 9, 2026', 'Saturday, January 10, 2026'],
        #   ...
        # ]
        currentDate = datetime.now().date()

        def indexOfClosestDate(groups: list[list[str]]) -> int:
            fmt = "%A, %B %d, %Y"
            allDates = []
            for i, group in enumerate(groups):
                for s in group:
                    d = datetime.strptime(s, fmt).date()
                    allDates.append((i, d))
            futureDates = [(i, d) for i, d in allDates if d >= currentDate]
            if not futureDates:
                closestGroupIndex, _ = min(allDates, key=lambda t: abs(t[1] - currentDate))
            else:
                closestGroupIndex, _ = min(futureDates, key=lambda t: t[1] - currentDate)
            return closestGroupIndex

        closestIndex = indexOfClosestDate(weekend_dates)
        thisWeekendDates = weekend_dates[closestIndex]

        if not thisWeekendDates:
            ui.label('No weekend games found.').classes('text-gray-500 mt-4')
            return

        def extractNewRefRecords(date: str) -> dict:
            """Extract games from ui.resultsFromRun and merge with all_match_data."""
            newRefRecords = {}
            def convertDate(date: str) -> str:
                return datetime.strptime(date, "%A, %B %d, %Y").strftime("%m/%d/%Y")
            def findGame(gameId: str, field: str) -> dict:
                #try:
                for game in self.all_match_data[date][field]:
                    if game['GameID'] == gameId:
                        return game
                return None
                #except KeyError:
                #    return None
            new_ref_names = {
                f'{firstname} {lastname}'.strip().lower()
                for firstname, lastname in self.db.getNewReferees(self._current_org_id())
            }
            def position_is_new(workload_game: dict, flag_key: str, crew_name: str) -> bool:
                if flag_key in workload_game:
                    return bool(workload_game[flag_key])
                return name_is_new_ref(crew_name, new_ref_names)
            dateToMatch = convertDate(date)
            for field in ui.resultsFromRun.keys():
                if field not in newRefRecords:
                    newRefRecords[field] = []
                for gameId, game in ui.resultsFromRun[field].items():
                    if game['date'] == dateToMatch:
                        allDataGame = findGame(gameId, field)

                        if allDataGame is not None:
                            display_game = dict(allDataGame)
                            display_game['already_mentored_center'] = game.get(
                                'already_mentored_center', game.get('cmarker') == '**')
                            display_game['already_mentored_ar1'] = game.get(
                                'already_mentored_ar1', game.get('a1marker') == '**')
                            display_game['already_mentored_ar2'] = game.get(
                                'already_mentored_ar2', game.get('a2marker') == '**')
                            display_game['needs_followup_center'] = game.get(
                                'needs_followup_center', game.get('crisky') == '##')
                            display_game['needs_followup_ar1'] = game.get(
                                'needs_followup_ar1', game.get('a1risky') == '##')
                            display_game['needs_followup_ar2'] = game.get(
                                'needs_followup_ar2', game.get('a2risky') == '##')
                            display_game['new_ref_center'] = position_is_new(
                                game, 'new_ref_center', display_game.get('Center'))
                            display_game['new_ref_ar1'] = position_is_new(
                                game, 'new_ref_ar1', display_game.get('AR1'))
                            display_game['new_ref_ar2'] = position_is_new(
                                game, 'new_ref_ar2', display_game.get('AR2'))
                            newRefRecords[field].append(display_game)

                if field in newRefRecords and len(newRefRecords[field]) == 0:
                    del newRefRecords[field]
            return newRefRecords

        # Check if resultsFromRun is available
        if not hasattr(ui, 'resultsFromRun') or ui.resultsFromRun is None:
            # Show loading state and poll for data
            loading_container = ui.column().classes('items-center justify-center p-8')
            with loading_container:
                ui.spinner(size='lg')
                ui.label('Loading workload data...').classes('mt-4 text-gray-600')
                ui.label('Please wait while the workload data is being generated.').classes('text-sm text-gray-500 mt-2')

            def check_results_ready():
                if self.ensure_workload:
                    try:
                        self.ensure_workload()
                    except Exception as e:
                        self.logger.debug('ensure_workload failed: %s', e)
                if hasattr(ui, 'resultsFromRun') and ui.resultsFromRun is not None:
                    loading_container.clear()
                    loading_container.classes('w-full')
                    with loading_container:
                        self._render_weekend_games(thisWeekendDates, extractNewRefRecords)
                else:
                    ui.timer(0.5, check_results_ready, once=True)

            ui.timer(0.5, check_results_ready, once=True)
            return

        self._render_weekend_games(thisWeekendDates, extractNewRefRecords)

    def _render_weekend_games(self, weekend_dates, extract_new_ref_records):
        """Render game sections for the weekend, or a clear message if none qualify."""
        rendered_any = False
        for date in weekend_dates:
            new_ref_records = extract_new_ref_records(date)
            if not new_ref_records:
                continue
            self._render_day_section(date, new_ref_records)
            rendered_any = True

        if not rendered_any:
            ui.label(
                'No games with new referees for the upcoming weekend. '
                'This is normal before the season starts or when the workload has no new-ref assignments.'
            ).classes('text-gray-500 mt-4')
