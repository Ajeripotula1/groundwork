"""
One module per resource - profile, jobs, companies, interview, etc. as
later slices add them. Each defines its own `router = APIRouter(...)` and
gets wired into the app once, in groundwork.api.main.

Splitting routers out like this (instead of every endpoint living directly
in main.py) is what keeps main.py readable as more slices add more
endpoints - Slice 6+ will add interview/cover-letter/companies routers
alongside this one without main.py growing route-handler bodies itself.
"""
