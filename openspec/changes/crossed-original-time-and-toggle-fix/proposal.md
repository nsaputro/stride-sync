# Proposal: Crossed Original Time and Toggle Rotation Fix

## Why
When workouts are overridden, athletes want to see the original Garmin planned duration crossed out before the overridden target, and cards without pace/heart-rate chips must not flip button text upside down when expanded.

## What Changes
- Query original Garmin planned duration and distance in upcoming workout plans query.
- Render crossed-out original target duration preceding the active target in the workout card header when overridden.
- Render coaching disclosure toggle with just the rotating chevron chip (or rotate only the arrow) so button labels never flip upside down when open.
- Add unit and integration tests covering crossed-out original target rendering and toggle disclosure behavior.
