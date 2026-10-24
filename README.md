SYSTEMS THINKING PORTAL — AS-IS / TO-BE + ACCOUNTS

ZIP CONTENTS
- app.py: Streamlit interface, login/registration, project saving, AS-IS and TO-BE workflow
- analysis_core.py: KSIM simulation and analysis functions
- requirements.txt: Python dependencies
- schema.sql: Supabase database tables and row-level security policies

IMPORTANT SETUP — LOGIN AND DATABASE
1. Create a project at https://supabase.com/ and wait until it is ready.
2. In Supabase, open SQL Editor, paste the complete schema.sql file, and run it.
3. In Supabase Project Settings / API, copy the Project URL and anon/publishable key. Do NOT use the service_role key in Streamlit.
4. In your Streamlit Cloud app, open Manage app > Settings > Secrets and add:

SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_ANON_KEY = "YOUR_SUPABASE_ANON_OR_PUBLISHABLE_KEY"

5. In your GitHub repository, replace app.py, analysis_core.py and requirements.txt with the versions in this ZIP. You may also add/replace schema.sql and README.txt for reference. Keep a backup of your existing repository before replacing files.
6. Since you have already created the tables and policies, do NOT rerun schema.sql just for this session fix. Run it only if you are setting up a fresh Supabase project or intentionally updating the database schema.
7. Commit the files and let Streamlit Cloud redeploy. Then refresh the portal and log in again.
8. Test personal project save/load and group isolation using two separate accounts before sharing the URL.

AUTH AND DATA NOTES
- Registration is open to anyone with the portal URL. Supabase may require email verification depending on its Auth settings.
- Project rows are stored in Supabase Postgres, not a local SQLite file.
- Row-level security (RLS) is intended to isolate personal projects and group projects.
- Do not put a Supabase service_role key in Streamlit secrets or client code.
- Existing projects in an old SQLite database are not automatically migrated into Supabase.
- Group creation and joining by a shareable join code are included. Group owners should share the code only with intended teammates. Group projects are visible to members; personal projects remain private. Do not disable RLS to make sharing work.

AS-IS / TO-BE FUNCTIONALITY
- AS-IS matrix is the baseline cross-impact matrix.
- TO-BE allows multiple selected interventions.
- For each selected intervention, specify a target, source and impact value. The Generate button applies these defined rules to the TO-BE matrix; it does not invent relationships.
- The TO-BE matrix remains manually editable after generation.
- Both simulations can be run and compared. Original variables are compared on common charts; new intervention variables appear in the TO-BE results.
- Time labels use T0, T1, T2, etc.
- Matrix impact values are constrained to [-1, +1] in this interface.

ACADEMIC METHODOLOGY
The existing core uses the documented simplified KSIM-style exponent variant already present in the source. Confirm the exact formula with the professor's workbook before treating its outputs as identical to the course's official method. The app does not silently create causal links; the student specifies their signs and strengths.

LIMITATIONS / TESTING
This ZIP has not been connected to your live Supabase project or tested in a deployed browser. After setup, test account registration, email confirmation, personal project save/load, group isolation, deletion permissions, and a small AS-IS/TO-BE test before relying on it for coursework. If Streamlit or Supabase reports an error, share the exact error text/screenshot so it can be fixed.
