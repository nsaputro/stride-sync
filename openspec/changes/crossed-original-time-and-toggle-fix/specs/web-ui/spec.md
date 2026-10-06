## MODIFIED Requirements

### Requirement: Running Analytics Tab
The Running tab SHALL display upcoming scheduled training plans with merged plan overrides at the very top of the tab using mobile-friendly expandable workout cards, followed by heart rate zone ranges and aggregate weekly mileage grouped Monday through Sunday with most recent weeks first.

#### Scenario: Viewing upcoming training plan
- **WHEN** the Running tab is opened
- **THEN** future scheduled workouts are rendered in expandable workout cards at the top of the tab, displaying dates, workout names, target metrics with crossed-out original planned targets for overrides, pace, heart rate, and override badges without horizontal overflow.

#### Scenario: Expanding coaching rationale on workout card
- **WHEN** a user taps or clicks on an overridden workout card's coaching disclosure
- **THEN** the coaching rationale, specific instructions, and superseded Garmin workout are revealed inline without rotating text upside down.

#### Scenario: Viewing weekly volume
- **WHEN** the Running tab is opened
- **THEN** weekly distances are displayed in chronological order (recent first) grouped by calendar week along with heart rate zone thresholds below the upcoming training plan.

#### Scenario: No upcoming workouts scheduled
- **WHEN** the Running tab is opened and no workouts are scheduled on or after the current date
- **THEN** an empty-state card indicating no upcoming workouts scheduled is rendered above heart rate zones.
