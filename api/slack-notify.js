/**
 * Furnace — Slack notification proxy
 * Vercel serverless function that relays chat.postMessage from server-side
 * to avoid browser CORS restrictions on the Slack Web API.
 *
 * POST /api/slack-notify
 * Body: { projName, projCode, token, type? }
 *   type: 'new_project' (default) | 'project_finished'
 */
module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ ok: false, error: 'method_not_allowed' });

  const { projName, projCode, token, type } = req.body || {};

  if (!token) return res.status(400).json({ ok: false, error: 'no_token' });
  if (!projName || !projCode) return res.status(400).json({ ok: false, error: 'missing_params' });

  let text;
  if (type === 'project_finished') {
    text = `✅ *Project Ready to Close in QuickBooks*\n*${projCode}* — ${projName}\nPlease close out this project in QuickBooks.`;
  } else {
    text = `📋 *New Project Created*\n*${projCode}* — ${projName}`;
  }

  const targets = ['U01TVP5C94N']; /* Richelle Butcher */

  let lastError = null;
  for (const channel of targets) {
    try {
      const slackResp = await fetch('https://slack.com/api/chat.postMessage', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ channel, text })
      });
      const data = await slackResp.json();
      if (!data.ok) {
        console.warn(`Slack DM failed for ${channel}:`, data.error);
        lastError = data.error;
      }
    } catch (e) {
      console.error('Slack fetch error:', e);
      lastError = e.message || 'fetch_failed';
    }
  }

  return res.status(200).json(lastError ? { ok: false, error: lastError } : { ok: true });
};
