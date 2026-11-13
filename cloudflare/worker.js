import { REPO, REF, dueWorkflows } from "./schedule.js";

export async function dispatch(workflow, token, fetchImpl = fetch) {
  const url = `https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`;
  const init = {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "tw-hold-alarm",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: REF }),
  };
  let status = 0;
  let detail = "";
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetchImpl(url, init);
      status = res.status;
      if (status === 204) {
        console.log(`dispatch ok: ${workflow}`);
        return { workflow, status, ok: true };
      }
      detail = String(await res.text()).slice(0, 200);
    } catch (e) {
      status = 0;
      detail = String(e && e.message).slice(0, 200);
    }
  }
  console.error(`dispatch failed: ${workflow} status=${status} ${detail}`);
  return { workflow, status, ok: false };
}

export default {
  async scheduled(event, env, ctx) {
    const when = new Date(event.scheduledTime);
    const due = dueWorkflows(when);
    if (due.length === 0) return;
    for (const w of due) {
      await dispatch(w, env.GH_TOKEN);
    }
  },
};
