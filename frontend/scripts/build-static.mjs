import { spawnSync } from "node:child_process";
const prefix = (process.env.OPS_PAGES_BASE || "").replace(/^\/+|\/+$/g, "");
for (const mode of ["evidence", "sandbox"]) {
  const result = spawnSync("npm", ["exec", "--", "vite", "build", "--outDir", `dist/${mode}`], {
    stdio: "inherit",
    env: {...process.env, VITE_APP_MODE: mode, VITE_BASE_PATH: `/${prefix ? `${prefix}/` : ""}${mode}/`},
  });
  if (result.status !== 0) process.exit(result.status || 1);
}
