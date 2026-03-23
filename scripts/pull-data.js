#!/usr/bin/env node

/**
 * Portfolio Data Puller
 * Pulls project effort spent and resource allocation data from Monday.com API
 * Writes consolidated data to data/portfolio.json
 */

const fs = require('fs');
const path = require('path');

const API_KEY = process.env.MONDAY_API_KEY;
const DRY_RUN = process.argv.includes('--dry-run');
const RESOURCE_WORKSPACE_ID = 11363816;
const USERS_BOARD_ID = 8987846359;

if (!API_KEY) {
  console.error('ERROR: MONDAY_API_KEY environment variable not set');
  process.exit(1);
}

// Paths
const dataDir = path.join(__dirname, '../data');
const portfolioPath = path.join(dataDir, 'portfolio.json');

/**
 * GraphQL query helper
 */
async function queryMonday(query, variables = {}) {
  const response = await fetch('https://api.monday.com/v2', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': API_KEY,
    },
    body: JSON.stringify({ query, variables }),
  });

  if (!response.ok) {
    throw new Error(`Monday.com API error: ${response.status} ${response.statusText}`);
  }

  const data = await response.json();

  if (data.errors) {
    throw new Error(`Monday.com GraphQL error: ${JSON.stringify(data.errors)}`);
  }

  return data.data;
}

/**
 * Load existing portfolio data
 */
function loadPortfolioData() {
  console.log('📂 Loading existing portfolio data...');
  const content = fs.readFileSync(portfolioPath, 'utf8');
  return JSON.parse(content);
}

/**
 * Build a map of boardId -> { clientId, projectId, phases }
 */
function buildBoardRegistry(portfolio) {
  const registry = {};

  portfolio.clients.forEach((client) => {
    client.projects.forEach((project) => {
      if (project.boardId) {
        registry[project.boardId] = {
          clientId: client.id,
          clientName: client.name,
          projectId: project.id,
          projectName: project.name,
          phases: project.phases,
        };
      }
    });
  });

  return registry;
}

/**
 * Fetch all items for a board with effort columns
 */
async function fetchBoardItems(boardId) {
  console.log(`  Fetching items for board ${boardId}...`);

  const query = `
    query($boardId: [Int!]!) {
      boards(ids: $boardId) {
        items_page(limit: 500) {
          cursor
          items {
            id
            name
            column_values {
              id
              value
            }
            subitems {
              id
              name
              column_values {
                id
                value
              }
            }
          }
        }
      }
    }
  `;

  const result = await queryMonday(query, { boardId });

  if (!result.boards || !result.boards[0]) {
    return [];
  }

  return result.boards[0].items_page.items || [];
}

/**
 * Parse number value from column
 */
function parseNumberValue(value) {
  if (!value) return 0;
  try {
    const parsed = JSON.parse(value);
    return parsed.number || 0;
  } catch {
    return 0;
  }
}

/**
 * Calculate effort spent for a board
 * Formula: sum of subitem billable hours (subitems' numbers__1) + pulse-level billable hours (numbers1__1)
 */
function calculateEffortSpent(items) {
  let totalEffort = 0;

  items.forEach((item) => {
    // Pulse-level billable hours (numbers1__1 column)
    const pulseHours = item.column_values.find((cv) => cv.id === 'numbers1__1');
    if (pulseHours) {
      totalEffort += parseNumberValue(pulseHours.value);
    }

    // Subitem billable hours (subitems' numbers__1 column)
    if (item.subitems && item.subitems.length > 0) {
      item.subitems.forEach((subitem) => {
        const subitemHours = subitem.column_values.find((cv) => cv.id === 'numbers__1');
        if (subitemHours) {
          totalEffort += parseNumberValue(subitemHours.value);
        }
      });
    }
  });

  return totalEffort;
}

/**
 * Fetch resource planner boards from Resource Management workspace
 */
async function fetchResourcePlannerBoards() {
  console.log(`📊 Fetching resource planner boards from workspace ${RESOURCE_WORKSPACE_ID}...`);

  const query = `
    query($workspaceId: Int!) {
      workspace(id: $workspaceId) {
        boards(limit: 500) {
          id
          name
        }
      }
    }
  `;

  const result = await queryMonday(query, { workspaceId: RESOURCE_WORKSPACE_ID });

  if (!result.workspace || !result.workspace.boards) {
    return [];
  }

  return result.workspace.boards;
}

/**
 * Fetch allocation items from a resource planner board
 */
async function fetchResourcePlannerItems(boardId, boardName) {
  try {
    const query = `
      query($boardId: [Int!]!) {
        boards(ids: $boardId) {
          items_page(limit: 500) {
            items {
              id
              name
              column_values {
                id
                value
                ... on BoardRelationValue {
                  display_value
                }
              }
            }
          }
        }
      }
    `;

    const result = await queryMonday(query, { boardId });

    if (!result.boards || !result.boards[0] || !result.boards[0].items_page) {
      return [];
    }

    return result.boards[0].items_page.items || [];
  } catch (error) {
    console.warn(`  ⚠️ Failed to fetch from resource board ${boardId} (${boardName}): ${error.message}`);
    return [];
  }
}

/**
 * Parse date value from column
 */
function parseDateValue(value) {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value);
    return parsed.date || null;
  } catch {
    return null;
  }
}

/**
 * Parse date range value from column
 */
function parseDateRangeValue(value) {
  if (!value) return { start: null, end: null };
  try {
    const parsed = JSON.parse(value);
    return {
      start: parsed.from || null,
      end: parsed.to || null,
    };
  } catch {
    return { start: null, end: null };
  }
}

/**
 * Get value from column_values array
 */
function getColumnValue(columnValues, columnId) {
  const col = columnValues.find((cv) => cv.id === columnId);
  return col ? col.value : null;
}

/**
 * Get display value (for board relations)
 */
function getDisplayValue(columnValues, columnId) {
  const col = columnValues.find((cv) => cv.id === columnId);
  return col ? col.display_value || col.value : null;
}

/**
 * Count working days between two dates (inclusive)
 */
function countWorkingDays(startDate, endDate) {
  const start = new Date(startDate);
  const end = new Date(endDate);
  let count = 0;

  const current = new Date(start);
  while (current <= end) {
    const dayOfWeek = current.getDay();
    // 0 = Sunday, 6 = Saturday
    if (dayOfWeek !== 0 && dayOfWeek !== 6) {
      count++;
    }
    current.setDate(current.getDate() + 1);
  }

  return count;
}

/**
 * Count overlapping working days between allocation range and week range
 */
function countOverlappingWorkingDays(allocStart, allocEnd, weekStart, weekEnd) {
  const allocStartDate = new Date(allocStart);
  const allocEndDate = new Date(allocEnd);
  const weekStartDate = new Date(weekStart);
  const weekEndDate = new Date(weekEnd);

  const overlapStart = allocStartDate > weekStartDate ? allocStartDate : weekStartDate;
  const overlapEnd = allocEndDate < weekEndDate ? allocEndDate : weekEndDate;

  if (overlapStart > overlapEnd) {
    return 0;
  }

  return countWorkingDays(overlapStart.toISOString().split('T')[0], overlapEnd.toISOString().split('T')[0]);
}

/**
 * Calculate allocation hours for a week
 */
function calculateAllocationHours(allocation, weekStart, weekEnd) {
  const effortPerDay = allocation.effortPerDay || 0;
  const totalEffort = allocation.totalEffort || 0;
  const selectedType = allocation.selectedType || 'Per day';

  const overlappingDays = countOverlappingWorkingDays(
    allocation.start,
    allocation.end,
    weekStart,
    weekEnd
  );

  if (overlappingDays === 0) {
    return 0;
  }

  if (selectedType === 'Per day') {
    return effortPerDay * overlappingDays;
  } else if (selectedType === 'Total') {
    const totalDays = countWorkingDays(allocation.start, allocation.end);
    if (totalDays === 0) return 0;
    return totalEffort * (overlappingDays / totalDays);
  }

  return 0;
}

/**
 * Process resource planner data
 */
async function processResourcePlanners(portfolio) {
  console.log('📅 Processing resource planner allocations...');

  const boards = await fetchResourcePlannerBoards();
  console.log(`  Found ${boards.length} resource planner boards`);

  const resourceAllocations = {};

  for (const board of boards) {
    const items = await fetchResourcePlannerItems(board.id, board.name);

    // Look for "Allocation" items
    const allocationItems = items.filter(
      (item) => item.name.toLowerCase().includes('allocation')
    );

    if (allocationItems.length === 0) {
      continue;
    }

    // Try to match board to a project
    let projectId = null;

    // First, try to find matching project by name or code
    for (const client of portfolio.clients) {
      for (const project of client.projects) {
        if (
          board.name.toLowerCase().includes(project.name.toLowerCase()) ||
          board.name.toLowerCase().includes(project.id.toLowerCase())
        ) {
          projectId = project.id;
          break;
        }
      }
      if (projectId) break;
    }

    if (!projectId) {
      console.log(`  ⚠️ Could not match resource board "${board.name}" to a project`);
      continue;
    }

    if (!resourceAllocations[projectId]) {
      resourceAllocations[projectId] = [];
    }

    // Process allocation items
    allocationItems.forEach((item) => {
      const personName = getDisplayValue(item.column_values, 'rp_assignee');
      const timeline = parseDateRangeValue(getColumnValue(item.column_values, 'rp_timeline'));
      const effortPerDay = parseNumberValue(getColumnValue(item.column_values, 'rp_effort_per_day'));
      const totalEffort = parseNumberValue(getColumnValue(item.column_values, 'rp_total_effort'));
      const selectedType = getColumnValue(item.column_values, 'rp_selected_effort');

      if (!personName || !timeline.start || !timeline.end) {
        return;
      }

      resourceAllocations[projectId].push({
        person: personName,
        start: timeline.start,
        end: timeline.end,
        effortPerDay,
        totalEffort,
        selectedType: selectedType === 'Per day' ? 'Per day' : 'Total',
      });
    });
  }

  return resourceAllocations;
}

/**
 * Calculate resource tracker weeks
 */
function calculateResourceTrackerWeeks(resourceAllocations, portfolio) {
  console.log('📈 Calculating weekly resource tracker data...');

  const weeks = [];
  const today = new Date();
  const startOfYear = new Date(today.getFullYear(), 0, 1);

  // Generate weeks for the year
  let currentDate = new Date(startOfYear);
  while (currentDate.getFullYear() === today.getFullYear()) {
    const dayOfWeek = currentDate.getDay();

    // Move to Monday of the week
    const monday = new Date(currentDate);
    monday.setDate(currentDate.getDate() - (dayOfWeek === 0 ? 6 : dayOfWeek - 1));

    const weekStart = monday.toISOString().split('T')[0];
    const weekEnd = new Date(monday.getTime() + 4 * 24 * 60 * 60 * 1000); // Friday
    const weekEndStr = weekEnd.toISOString().split('T')[0];

    const label = `${monday.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${weekEnd.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;

    const weekData = {
      label,
      monday: weekStart,
      people: {},
    };

    // Aggregate allocations by person and project
    for (const projectId in resourceAllocations) {
      const allocations = resourceAllocations[projectId];

      allocations.forEach((allocation) => {
        if (!weekData.people[allocation.person]) {
          weekData.people[allocation.person] = {
            predicted: 0,
            actual: 0,
            projects: {},
          };
        }

        const hours = calculateAllocationHours(allocation, weekStart, weekEndStr);
        if (hours > 0) {
          weekData.people[allocation.person].predicted += hours;
          if (!weekData.people[allocation.person].projects[projectId]) {
            weekData.people[allocation.person].projects[projectId] = {
              p: hours,
              a: 0,
            };
          } else {
            weekData.people[allocation.person].projects[projectId].p += hours;
          }
        }
      });
    }

    if (Object.keys(weekData.people).length > 0) {
      weeks.push(weekData);
    }

    currentDate.setDate(currentDate.getDate() + 7);
  }

  return weeks;
}

/**
 * Update portfolio with effort spent data
 */
function updateEffortSpent(portfolio, boardRegistry, boardEffortMap) {
  console.log('💾 Updating effort spent data...');

  let updateCount = 0;

  portfolio.clients.forEach((client) => {
    client.projects.forEach((project) => {
      if (project.boardId && boardEffortMap[project.boardId] !== undefined) {
        const newEffort = boardEffortMap[project.boardId];

        // Distribute effort across phases proportionally or mark phase as having effort
        if (project.phases && project.phases.length > 0) {
          // For now, just update the first phase if it has no spent data
          // In reality, we'd need more granular phase tracking from Monday.com

          // Check if any phase already has spent data
          const hasSpentData = project.phases.some((p) => p.spent && p.spent > 0);

          if (!hasSpentData && newEffort > 0) {
            // If no phase has spent data, update the first active/completed phase
            const targetPhase = project.phases.find(
              (p) => p.status === 'active' || p.status === 'completed'
            );
            if (targetPhase) {
              const oldEffort = targetPhase.spent || 0;
              targetPhase.spent = newEffort;
              if (newEffort !== oldEffort) {
                updateCount++;
                console.log(`  Updated ${project.name}: ${oldEffort} → ${newEffort} hours`);
              }
            }
          }
        }
      }
    });
  });

  console.log(`  Updated ${updateCount} projects with new effort data`);
}

/**
 * Main function
 */
async function main() {
  try {
    console.log('🚀 Starting portfolio data pull...\n');

    if (DRY_RUN) {
      console.log('🔍 DRY RUN MODE - Reading existing data only\n');
    }

    // Load existing portfolio
    const portfolio = loadPortfolioData();
    const boardRegistry = buildBoardRegistry(portfolio);

    console.log(`📋 Found ${Object.keys(boardRegistry).length} boards in registry\n`);

    // Fetch effort spent for all boards
    const boardEffortMap = {};

    for (const boardId in boardRegistry) {
      try {
        const items = await fetchBoardItems(parseInt(boardId));
        const effort = calculateEffortSpent(items);
        boardEffortMap[boardId] = effort;
        console.log(`  Board ${boardId}: ${effort} hours`);
      } catch (error) {
        console.warn(`  ⚠️ Failed to fetch board ${boardId}: ${error.message}`);
      }
    }

    console.log();

    // Process resource planner data
    let resourceAllocations = {};
    let resourceTrackerWeeks = [];

    try {
      resourceAllocations = await processResourcePlanners(portfolio);
      console.log(`  Processed allocations for ${Object.keys(resourceAllocations).length} projects\n`);

      // Calculate tracker weeks
      resourceTrackerWeeks = calculateResourceTrackerWeeks(resourceAllocations, portfolio);
      console.log(`  Generated ${resourceTrackerWeeks.length} weeks of data\n`);
    } catch (error) {
      console.warn(`⚠️ Failed to process resource planners: ${error.message}`);
    }

    if (!DRY_RUN) {
      // Update effort spent
      updateEffortSpent(portfolio, boardRegistry, boardEffortMap);

      // Merge resource allocation data
      const existingAllocations = portfolio.resourceAllocations || {};
      portfolio.resourceAllocations = {
        ...existingAllocations,
        ...resourceAllocations,
      };

      // Update tracker weeks
      portfolio.resourceTrackerWeeks = resourceTrackerWeeks;

      // Update timestamp
      portfolio.lastUpdated = new Date().toISOString();

      // Write back to file
      fs.writeFileSync(portfolioPath, JSON.stringify(portfolio, null, 2) + '\n');
      console.log('✅ Portfolio data saved to data/portfolio.json');
    } else {
      console.log('✅ Dry run complete - no changes made');
    }

  } catch (error) {
    console.error('\n❌ Error:', error.message);
    process.exit(1);
  }
}

main();
