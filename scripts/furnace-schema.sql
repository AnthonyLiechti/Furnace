-- ============================================================
-- FURNACE DATABASE SCHEMA
-- Run this in Supabase Dashboard > SQL Editor
-- https://supabase.com/dashboard/project/jnwdscddyqujjikesdpb/sql
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- CLIENTS
-- ============================================================
CREATE TABLE clients (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  client_number TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  color TEXT DEFAULT '#306D7C',
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PROJECTS
-- ============================================================
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
  project_code TEXT NOT NULL,
  campaign_code TEXT,
  project_number TEXT,
  name TEXT NOT NULL,
  status TEXT DEFAULT 'active' CHECK (status IN ('inquiry','discovery','proposed','active','closeout','complete')),
  project_type TEXT DEFAULT 'billable' CHECK (project_type IN ('billable','bizdev','internal','small_projects')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_projects_code ON projects(project_code);

-- ============================================================
-- TEAM MEMBERS
-- ============================================================
CREATE TABLE team_members (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  department TEXT CHECK (department IN ('Executive/Admin','Account','Creative','Post')),
  employment_type TEXT DEFAULT 'Employee' CHECK (employment_type IN ('Employee','Freelancer')),
  billable_rate NUMERIC DEFAULT 185,
  fully_burdened_rate NUMERIC DEFAULT 185,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- BUDGETS
-- ============================================================
CREATE TABLE budgets (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  estimate_number INTEGER,
  name TEXT NOT NULL,
  status TEXT DEFAULT 'active' CHECK (status IN ('inquiry','discovery','proposed','active','closeout','complete')),
  client_price NUMERIC DEFAULT 0,
  total_amount NUMERIC DEFAULT 0,
  has_discount BOOLEAN DEFAULT FALSE,
  discount_percentage NUMERIC DEFAULT 0,
  reserve_percentage NUMERIC DEFAULT 10,
  oop_markup_percentage NUMERIC DEFAULT 20,
  notes TEXT,
  visibility TEXT DEFAULT 'visible',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  created_by UUID,
  updated_by UUID
);

-- ============================================================
-- LABOR BUDGET ENTRIES
-- ============================================================
CREATE TABLE labor_budget_entries (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  budget_id UUID REFERENCES budgets(id) ON DELETE CASCADE,
  team_member_id UUID REFERENCES team_members(id),
  employment_type TEXT,
  department TEXT,
  phase1 NUMERIC DEFAULT 0,
  phase2 NUMERIC DEFAULT 0,
  phase3_1 NUMERIC DEFAULT 0,
  phase3_2 NUMERIC DEFAULT 0,
  phase4 NUMERIC DEFAULT 0,
  phase5 NUMERIC DEFAULT 0,
  billable_percentage NUMERIC DEFAULT 100,
  rate_multiplier NUMERIC DEFAULT 1,
  rate_override NUMERIC,
  ad_hoc_rate NUMERIC,
  display_order INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_labor_budget ON labor_budget_entries(budget_id);

-- ============================================================
-- OOP SECTIONS
-- ============================================================
CREATE TABLE oop_sections (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  display_order INTEGER DEFAULT 0
);

INSERT INTO oop_sections (name, slug, display_order) VALUES
  ('Creative', 'creative', 1),
  ('Camera', 'camera', 2),
  ('Talent', 'talent', 3),
  ('Travel & Meals', 'travel-meals', 4);

-- ============================================================
-- OOP CATEGORIES
-- ============================================================
CREATE TABLE oop_categories (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  section_id UUID REFERENCES oop_sections(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  display_order INTEGER DEFAULT 0
);

INSERT INTO oop_categories (section_id, name, display_order)
SELECT s.id, c.name, c.ord FROM oop_sections s,
  (VALUES ('Creative',1),('Production Design',2),('Hair/Makeup/Glam',3),
          ('Wardrobe',4),('Facilities/Location',5),('Other',6)) AS c(name,ord)
WHERE s.slug = 'creative';

INSERT INTO oop_categories (section_id, name, display_order)
SELECT s.id, c.name, c.ord FROM oop_sections s,
  (VALUES ('Production Crew',1),('Camera Crew',2),('Grip and Electric',3),
          ('Sound',4),('Camera Rental',5),('Other',6)) AS c(name,ord)
WHERE s.slug = 'camera';

INSERT INTO oop_categories (section_id, name, display_order)
SELECT s.id, c.name, c.ord FROM oop_sections s,
  (VALUES ('Casting',1),('Principal Talent',2),('Extras',3),
          ('Narrator',4),('Pets',5),('Other',6)) AS c(name,ord)
WHERE s.slug = 'talent';

INSERT INTO oop_categories (section_id, name, display_order)
SELECT s.id, c.name, c.ord FROM oop_sections s,
  (VALUES ('Travel',1),('Accommodations',2),('Meals',3)) AS c(name,ord)
WHERE s.slug = 'travel-meals';

-- ============================================================
-- OOP BUDGET ENTRIES (3-tier: Planned / Adjusted / Actual)
-- ============================================================
CREATE TABLE oop_budget_entries (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  budget_id UUID REFERENCES budgets(id) ON DELETE CASCADE,
  section_id UUID REFERENCES oop_sections(id),
  category_id UUID REFERENCES oop_categories(id),
  line_item_name TEXT NOT NULL,

  count INTEGER DEFAULT 0,
  rate NUMERIC DEFAULT 0,
  days INTEGER DEFAULT 1,
  head_count INTEGER DEFAULT 1,

  adjusted_count INTEGER,
  adjusted_rate NUMERIC,
  adjusted_days INTEGER,
  adjusted_head_count INTEGER,

  actual_count INTEGER,
  actual_rate NUMERIC,
  actual_days INTEGER,
  actual_head_count INTEGER,
  actual_amount NUMERIC,

  is_active BOOLEAN DEFAULT TRUE,
  notes TEXT,
  display_order INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_oop_budget ON oop_budget_entries(budget_id);

-- ============================================================
-- LABOR ACTUALS
-- ============================================================
CREATE TABLE labor_actuals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  budget_id UUID REFERENCES budgets(id) ON DELETE CASCADE,
  team_member_id UUID REFERENCES team_members(id),
  hours NUMERIC NOT NULL DEFAULT 0,
  billable_rate NUMERIC,
  phase_key TEXT,
  work_date DATE,
  synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_labor_actuals_budget ON labor_actuals(budget_id);

-- ============================================================
-- EXPENSE ACTUALS
-- ============================================================
CREATE TABLE expense_actuals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  budget_id UUID REFERENCES budgets(id) ON DELETE CASCADE,
  amount NUMERIC NOT NULL DEFAULT 0,
  expense_category TEXT,
  description TEXT,
  work_date DATE,
  synced_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- BUDGET PHASE COMPLETION
-- ============================================================
CREATE TABLE budget_phase_completion (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  budget_id UUID REFERENCES budgets(id) ON DELETE CASCADE,
  phase_key TEXT NOT NULL,
  completion_percentage NUMERIC DEFAULT 0,
  UNIQUE(budget_id, phase_key)
);

-- ============================================================
-- AGENCY SETTINGS
-- ============================================================
CREATE TABLE agency_settings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  category TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT,
  sort_order INTEGER DEFAULT 0,
  UNIQUE(category, key)
);

INSERT INTO agency_settings (category, key, value, sort_order) VALUES
  ('markup', 'oop_markup_percentage', '20', 1),
  ('rates', 'default_employee_rate', '185', 1),
  ('rates', 'default_freelancer_rate', '250', 2),
  ('reserve', 'reserve_percentage', '10', 1),
  ('discount', 'default_discount', '3.5', 1);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE labor_budget_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE oop_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE oop_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE oop_budget_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE labor_actuals ENABLE ROW LEVEL SECURITY;
ALTER TABLE expense_actuals ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_phase_completion ENABLE ROW LEVEL SECURITY;
ALTER TABLE agency_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "auth_all" ON clients FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON projects FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON team_members FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON budgets FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON labor_budget_entries FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON oop_sections FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON oop_categories FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON oop_budget_entries FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON labor_actuals FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON expense_actuals FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON budget_phase_completion FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_all" ON agency_settings FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "anon_read" ON oop_sections FOR SELECT USING (true);
CREATE POLICY "anon_read" ON oop_categories FOR SELECT USING (true);
CREATE POLICY "anon_read" ON agency_settings FOR SELECT USING (true);
