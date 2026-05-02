const { spawnSync } = require("node:child_process");

delete process.env.npm_config_workspace;
delete process.env.npm_config_workspaces;

const result = spawnSync("next build", {
  stdio: "inherit",
  env: process.env,
  shell: true
});

if (result.error) {
  console.error(result.error.message);
}

process.exit(result.status ?? 1);
