#!/usr/bin/env node
/**
 * Furnace → Supabase Migration Script
 * Migrates portfolio.json, allocations.json, actuals.json, oop-schedule.json into Supabase.
 *
 * Prerequisites:
 *   1. Run the SQL block from the migration guide in Supabase SQL Editor first.
 *   2. Node.js 18+ (uses built-in fetch).
 *
 * Usage:
 *   node scripts/migrate.js
 */

const fs = require('fs');
const path = require('path');

const SUPABASE_URL = 'https://jnwdscddyqujjikesdpb.supabase.co';
const ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Impud2RzY2RkeXF1amppa2VzZHBiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQyODgxOTEsImV4cCI6MjA4OTg2NDE5MX0.EQueTlfX30ULmpLDF7ijSv0xR0_baAT2kPjYoK_RnpA';
const DATA_DIR = path.join(__dirname, '..', 'data');

/* ── Supabase helpers ── */
async function supa(table, query = '', method = 'GET', body = null) {
  const url = `${SUPABASE_URL}/rest/v1/${table}${query ? '?' + query : ''}`;
  const opts = {
    method,
    headers: {
      'apikey': ANON_KEY,
      'Authorization': `Bearer ${ANON_KEY}`,
      'Content-Type': 'application/json',
      'Prefer': (method === 'POST' || method === 'PATCH') ? 'return=representation' : 'return=minimal'
    }
  };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    const text = await resp.text();
    console.error(`  ❌ ${method} ${table}: ${resp.status} ${text.slice(0, 300)}`);
    return null;
  }
  const text = await resp.text();
  return text ? JSON.parse(text) : null;
}

async function supaAll(table, query = '') {
  const results = [];
  let offset = 0;
  const limit = 1000;
  while (true) {
    const chunk = await supa(table, `${query ? query + '&' : ''}limit=${limit}&offset=${offset}`);
    if (!chunk || chunk.length === 0) break;
    results.push(...chunk);
    if (chunk.length < limit) break;
    offset += limit;
  }
  return results;
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

/* ── Main ── */
async function main() {
  console.log('🔥 Furnace Migration Starting...\n');

  /* Load JSON files */
  const portfolio  = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'portfolio.json'),  'utf8'));
  const allocFile  = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'allocations.json'),'utf8'));
  const actualsFile= JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'actuals.json'),    'utf8'));
  const oopFile    = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'oop-schedule.json'),'utf8'));

  /* ── Prefetch existing Supabase data ── */
  console.log('📋 Prefetching existing Supabase data...');
  const existingClients  = await supaAll('clients',  'select=id,client_number');
  const clientByCode = {};
  for (const c of existingClients) clientByCode[c.client_number] = c;

  const existingProjects = await supaAll('projects', 'select=id,project_code,display_id');
  const projectByCode = {};
  for (const p of existingProjects) projectByCode[p.project_code] = p;

  const existingBudgets  = await supaAll('budgets',  'select=id,project_id');
  const budgetByProjId = {};
  for (const b of existingBudgets) budgetByProjId[b.project_id] = b;

  const teamMembers = await supaAll('team_members', 'select=id,name');
  const tmByName = {};
  for (const tm of teamMembers) tmByName[tm.name.toLowerCase().trim()] = tm.id;

  const existingLabor = await supaAll('labor_budget_entries', 'select=budget_id,team_member_id');
  const laborSet = new Set(existingLabor.map(l => `${l.budget_id}:${l.team_member_id}`));

  console.log(`  ${existingClients.length} clients, ${existingProjects.length} projects, ${existingBudgets.length} budgets, ${teamMembers.length} team members\n`);

  /* ── STEP 1: Clients + Projects + Budgets + Labor ── */
  console.log('📁 Migrating clients and projects...');
  let stats = { clientsNew:0, clientsUpdated:0, projNew:0, projUpdated:0, budgetsNew:0, laborNew:0, laborSkipped:0 };

  for (const client of portfolio.clients) {
    /* Upsert client */
    let clientRec = clientByCode[client.code];
    if (!clientRec) {
      const res = await supa('clients', '', 'POST', {
        name: client.name,
        client_number: client.code,
        color: client.color || '#306D7C',
        client_status: client.status || 'active'
      });
      if (res && res[0]) { clientRec = res[0]; clientByCode[client.code] = clientRec; stats.clientsNew++; }
      else { console.warn(`  ⚠️  Could not create client ${client.code}`); continue; }
    } else {
      await supa(`clients?id=eq.${clientRec.id}`, '', 'PATCH', {
        color: client.color || '#306D7C',
        client_status: client.status || 'active'
      });
      stats.clientsUpdated++;
    }

    for (const proj of client.projects) {
      /* Upsert project */
      let projRec = projectByCode[proj.code];
      const projPayload = {
        name: proj.name,
        project_code: proj.code,
        client_id: clientRec.id,
        project_status: proj.status || 'active',
        board_id: proj.boardId || null,
        hour_type: proj.hourType || 'billable',
        project_type: proj.projectType || null,
        snapshot_url: proj.snapshotUrl || null,
        display_id: proj.id,
        dollar_budget: proj.dollarBudget || 0,
        labor_cost_snapshot: proj.laborCost || 0,
        oop_cost_snapshot: proj.oopCost || 0,
        phases_snapshot: JSON.stringify(proj.phases || []),
        has_budget_data: proj.hasBudgetData || false
      };

      if (!projRec) {
        const res = await supa('projects', '', 'POST', projPayload);
        if (res && res[0]) { projRec = res[0]; projectByCode[proj.code] = projRec; stats.projNew++; }
        else { console.warn(`  ⚠️  Could not create project ${proj.code}`); continue; }
      } else {
        /* Patch metadata but preserve existing display_id if set */
        const patch = { ...projPayload };
        if (projRec.display_id) delete patch.display_id;
        await supa(`projects?id=eq.${projRec.id}`, '', 'PATCH', patch);
        stats.projUpdated++;
      }

      /* Create a budget for historical projects if none exists yet */
      if (proj.hasBudgetData && !budgetByProjId[projRec.id]) {
        const bStatus = (proj.status === 'finished' || proj.status === 'complete') ? 'closeout' : 'active';
        const bRes = await supa('budgets', '', 'POST', {
          name: proj.name,
          project_id: projRec.id,
          status: bStatus,
          visibility: 'visible',
          client_price: proj.dollarBudget || 0,
          total_amount: (proj.laborCost || 0) + (proj.oopCost || 0)
        });
        if (bRes && bRes[0]) {
          const budget = bRes[0];
          budgetByProjId[projRec.id] = budget;
          stats.budgetsNew++;

          /* Labor entries from snapshot.people */
          const people = (proj.snapshot && proj.snapshot.people) || proj.people || [];
          let order = 0;
          for (const person of people) {
            const hrs = person.hours || person.spent || 0;
            if (hrs <= 0) continue;
            const tmId = tmByName[person.name.toLowerCase().trim()];
            if (!tmId) { stats.laborSkipped++; continue; }
            const key = `${budget.id}:${tmId}`;
            if (laborSet.has(key)) continue;
            await supa('labor_budget_entries', '', 'POST', {
              budget_id: budget.id,
              team_member_id: tmId,
              phase1: hrs,
              display_order: order++
            });
            laborSet.add(key);
            stats.laborNew++;
            await sleep(40);
          }
        }
      }
      await sleep(25);
    }
  }

  console.log(`  ✅ Clients: ${stats.clientsNew} new, ${stats.clientsUpdated} updated`);
  console.log(`  ✅ Projects: ${stats.projNew} new, ${stats.projUpdated} updated`);
  console.log(`  ✅ Budgets: ${stats.budgetsNew} new`);
  console.log(`  ✅ Labor entries: ${stats.laborNew} new, ${stats.laborSkipped} skipped (name not matched)\n`);

  /* ── STEP 2: Allocations ── */
  /* Deduplicate on person+project+date since the JSON IDs are text, not UUIDs */
  console.log('📅 Migrating allocations...');
  const existingAllocs = await supaAll('allocations', 'select=person,project,date');
  const allocKeySet = new Set(existingAllocs.map(a => `${a.person}|${a.project}|${a.date}`));

  const newAllocs = (allocFile.allocations || [])
    .filter(a => !allocKeySet.has(`${a.person}|${a.project}|${a.date}`))
    .map(a => ({
      /* Omit id — let Supabase generate a UUID */
      person: a.person,
      project: a.project,
      date: a.date,
      hours_per_day: a.hoursPerDay,
      week_of: a.weekOf,
      total_hours: a.totalHours || a.hoursPerDay,
      days: a.days || 1,
      notes: a.notes || ''
    }));

  let allocsCreated = 0;
  for (let i = 0; i < newAllocs.length; i += 200) {
    const res = await supa('allocations', '', 'POST', newAllocs.slice(i, i + 200));
    if (res !== null) allocsCreated += Math.min(200, newAllocs.length - i);
    await sleep(300);
  }
  console.log(`  ✅ Allocations: ${allocsCreated} new, ${existingAllocs.length} already existed\n`);

  /* ── STEP 3: Actuals (actuals.json weeks → labor_actuals) ── */
  console.log('⏱️  Migrating actuals...');
  const existingAct = await supaAll('labor_actuals', "select=work_date,person_name,board_name&source=eq.actuals_json");
  const actSet = new Set(existingAct.map(a => `${a.work_date}:${a.person_name}:${a.board_name}`));

  /* Build project name → code lookup */
  const nameToCode = {};
  for (const client of portfolio.clients)
    for (const proj of client.projects)
      nameToCode[proj.name.toLowerCase()] = proj.code;

  const actBatch = [];
  for (const week of actualsFile.weeks || []) {
    for (const [person, pData] of Object.entries(week.people || {})) {
      for (const [projName, hours] of Object.entries(pData.projects || {})) {
        const key = `${week.weekOf}:${person}:${projName}`;
        if (actSet.has(key)) continue;
        actBatch.push({
          person_name: person,
          board_name: projName,
          project_code: nameToCode[projName.toLowerCase()] || null,
          hours: hours,
          work_date: week.weekOf,
          source: 'actuals_json',
          is_billable: !projName.toLowerCase().includes('non-billable') && !projName.toLowerCase().includes('internal'),
          is_timeoff: projName.toLowerCase().includes('time off')
        });
      }
    }
  }

  let actsCreated = 0;
  for (let i = 0; i < actBatch.length; i += 200) {
    await supa('labor_actuals', '', 'POST', actBatch.slice(i, i + 200));
    actsCreated += Math.min(200, actBatch.length - i);
    await sleep(300);
  }
  console.log(`  ✅ Actuals: ${actsCreated} new entries\n`);

  /* ── STEP 4: OOP Payment Schedule ── */
  console.log('💰 Migrating OOP payment schedule...');
  const existingPay = await supaAll('payment_schedule', 'select=id');
  const payIdSet = new Set(existingPay.map(p => p.id));

  let paymentsCreated = 0;
  for (const entry of oopFile.entries || []) {
    if (payIdSet.has(entry.id)) continue;
    await supa('payment_schedule', '', 'POST', {
      id: entry.id,
      project_code: entry.projectCode,
      project_name: entry.projectName,
      line_item_name: entry.lineItemName,
      amount: entry.amount || 0,
      scheduled_date: entry.date || null,
      week_of: entry.weekOf || null,
      paid: entry.paid || false,
      notes: entry.notes || '',
      supa_oop_id: entry.supaOopId || null
    });
    paymentsCreated++;
    await sleep(50);
  }
  console.log(`  ✅ Payment schedule: ${paymentsCreated} new, ${existingPay.length} already existed\n`);

  console.log('🎉 Migration complete!\n');
  console.log('Deploy the updated index.html, then verify everything loads from Supabase.');
}

main().catch(err => { console.error('\n💥 Migration failed:', err); process.exit(1); });
