SYSTEMS THINKING ANALYSIS PORTAL — REBUILD
==========================================

WHAT IS INCLUDED
----------------
app.py                     Streamlit portal with individual login, matrix upload/editing,
                           professor-aligned KSIM, interventions, comparisons and exports.
analysis_core.py           KSIM calculation engine, matrix/template helpers and reference checks.
schema.sql                 Fresh Supabase schema for individual private projects only.
requirements.txt           Python dependencies for Streamlit Cloud.
runtime.txt                Python runtime hint.
.streamlit/config.toml      UI theme settings.
tests/test_ksim.py         Automated formula/reference tests.

IMPORTANT MODEL CONVENTION
--------------------------
The portal follows the formula in the supplied professor workbook:

  numerator_i(t)   = 1 + (dt/2) * SUM_j[(ABS(a_ij) - a_ij) * x_j(t)]
  denominator_i(t) = 1 + (dt/2) * SUM_j[(ABS(a_ij) + a_ij) * x_j(t)]
  p_i(t)            = numerator_i(t) / denominator_i(t)
  x_i(t+dt)         = x_i(t) ** p_i(t)

Matrix rows are the affected/target variables; columns are the influencing/source variables.
States are normalized to [0,1] using the configured minimum and maximum. The app includes
reference tests matching the supplied workbook's baseline T0->T1 values, intervention T0->T1
values, beetle activation at T4, and intervention T4->T5 values. Use the in-app "Run professor
formula check" button after deployment. This checks the known reference points; it does not
replace reviewing assumptions and later trajectories for your own model.

MULTIPLE INTERVENTIONS
----------------------
Each intervention may add a variable or modify one or more relationships. Relationship rows
have their own activation period, separate from the introduction period of a new variable.
For up to six enabled interventions, the app calculates each intervention individually and every
combination of two or more. With more than six enabled interventions, it calculates individual
scenarios plus the full combined scenario to prevent an explosion in the number of runs.
If two selected interventions assign different values to the same matrix cell, the combined
scenario stops with a conflict message instead of silently choosing a value.

SET UP A NEW SUPABASE PROJECT (INDIVIDUAL ACCOUNTS ONLY)
--------------------------------------------------------
1. Go to https://supabase.com and create a NEW project. Choose a strong database password and
   keep it private. Wait until the project is ready.
2. In Supabase, open SQL Editor, create a new query, open schema.sql from this ZIP, copy its full
   contents into the SQL Editor, and click Run. It creates only the projects table and individual
   row-level security policies. There are no groups or group-membership tables.
3. In Supabase, open Project Settings / API Keys (the UI wording can vary). Copy the Project URL
   and the publishable key (the key may start with sb_publishable_). Do NOT use or share a secret
   key, service_role key, password, access token, or refresh token.
4. Open your Streamlit app settings (Manage app -> Settings -> Secrets) and add these two lines,
   replacing the quoted placeholders with your own values:

   SUPABASE_URL = "https://YOUR-PROJECT-REF.supabase.co"
   SUPABASE_ANON_KEY = "YOUR_SUPABASE_PUBLISHABLE_KEY"

   Despite the legacy variable name SUPABASE_ANON_KEY, the value is the public/publishable key.
   Never put a Supabase secret/service_role key in Streamlit Secrets for this app.
5. Deploy the files from this ZIP to a GitHub repository connected to Streamlit Community Cloud.
   Keep app.py, analysis_core.py, requirements.txt, runtime.txt, schema.sql and README.txt in the
   repository root; also upload the .streamlit folder.
6. In Streamlit Cloud, set the main file path to app.py and deploy/reboot the app.
7. Create an account in the app. If Supabase email confirmation is enabled, open the confirmation
   email before logging in. Then test login, save a project, reload it, and log out.
8. Use the in-app "Run professor formula check" button. It should report that the baseline and
   intervention reference checks pass.

GITHUB UPDATE / REDEPLOY
------------------------
- Extract the ZIP.
- Upload/replace all included files in your connected GitHub repository. Keep .streamlit/config.toml
  in the .streamlit folder; GitHub may hide dot-folders until you upload them explicitly.
- Commit the changes. Streamlit Cloud normally redeploys automatically; use Reboot if necessary.
- For a clean reset, create the new Supabase project first and configure its secrets before testing.
  Do not paste credentials into app.py, README, or a public GitHub commit.

MATRIX TEMPLATE
---------------
Use the portal's "Download Excel matrix template" button. It contains:
- AS-IS Matrix: square matrix with identical row and column variable labels.
- Initial Values: initial value, minimum, maximum for every variable.
- Read Me: matrix convention and formula.
You can upload the filled Excel file or export/edit a CSV matrix. All matrix cells must be numeric
and within -1 to +1. Variable labels must match exactly in rows and columns.

HOW TO USE THE PORTAL
---------------------
1. Log in and choose New project.
2. In Define & upload, enter a problem statement and variables, upload a matrix or edit cells,
   and optionally download a template. Use "Load professor's Parthenium example" to load the
   reference baseline and one intervention setup for testing.
3. In AS-IS analysis, set each variable's initial value/minimum/maximum and the simulation periods
   and dt. Click Run AS-IS baseline. Review trajectories, values, and numerator/denominator/exponent
   calculations.
4. In TO-BE interventions, add rows. Choose New variable or Modify existing relationships, set a
   start period, and describe the rationale. Add relationship rows that name the affected variable
   (row), influencing variable (column), impact, and period when that relationship becomes active.
5. In Compare & export, click Run individual interventions and combinations. For up to six enabled
   interventions, every individual and multi-intervention combination is calculated. Select which
   scenarios and variables to display in the graphs. Inspect the difference-from-baseline plot,
   matrix heatmap, calculation tables, summary, and export workbook.
6. Save project to your individual account.

TROUBLESHOOTING
---------------
- "permission denied": confirm schema.sql ran in the NEW Supabase project, the app uses that
  project's URL/publishable key, and you logged in again after changing Secrets. Do not disable RLS
  or grant project-table access to anon to work around this.
- Sign-up says to check email: confirm the email if confirmation is enabled, then log in.
- Matrix validation fails: row and column names must match exactly and every cell must be numeric.
- Scenario conflict: two selected interventions change the same matrix cell to different values.
  Resolve the relationship definitions explicitly.
- New variable appears at the wrong time: check its Start period; relationship activation time is
  configured separately in the relationship table.
- KSIM differs from the professor workbook: first run the reference check. Then verify the matrix,
  initial values, dt, intervention matrix changes, and variable activation time. Do not alter the
  formula merely to make graphs look more desirable.

SECURITY
--------
- Supabase Auth handles passwords; this app does not store passwords in the projects table.
- Row-level security restricts project rows to the signed-in user.
- The publishable key is intended for client use only with RLS policies. A secret/service_role key
  bypasses RLS and must never be used in this app.
- Do not commit Streamlit secrets or personal data to GitHub.
