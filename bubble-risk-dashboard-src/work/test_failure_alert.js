const assert = require('assert');
const fs = require('fs');
const path = require('path');

async function main() {
  const workflow = fs.readFileSync(path.resolve(__dirname, '../../.github/workflows/bubble-risk-dashboard.yml'), 'utf8');
  const match = workflow.match(/          script: \|\r?\n((?:            .*\r?\n|\r?\n)+)/);
  assert(match, 'notification script missing');
  const source = match[1].split(/\r?\n/).map(line => line.replace(/^ {12}/, '')).join('\n');
  const run = new (Object.getPrototypeOf(async function() {}).constructor)('github', 'context', 'core', source);
  const context = {repo: {owner: 'owner', repo: 'repo'}, runId: 123, serverUrl: 'https://github.com'};
  const created = [];
  let existing = [];
  const github = {
    rest: {issues: {listForRepo: () => {}, create: async args => created.push(args)}},
    paginate: async () => existing,
  };
  const core = {info: () => {}};
  await run(github, context, core);
  assert.strictEqual(created.length, 1);
  assert.deepStrictEqual(created[0].assignees, ['owner']);
  assert(created[0].body.includes('/owner/repo/actions/runs/123'));
  existing = [{title: created[0].title}];
  await run(github, context, core);
  assert.strictEqual(created.length, 1, 'duplicate alert created');
  existing = [];
  github.rest.issues.create = async () => { throw new Error('permission denied'); };
  await assert.rejects(run(github, context, core), /permission denied/);
  console.log('Failure notification: create, deduplicate, and error propagation passed');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
