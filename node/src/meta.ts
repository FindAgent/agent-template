import { readFileSync } from "node:fs";

interface PackageJson {
  name: string;
  version: string;
  repository?: { url?: string };
}

/** Read once from the package.json next to dist/ (and src/), so the version has one source. */
const pkg = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf-8"),
) as PackageJson;

export const AGENT_NAME: string = pkg.name;
export const AGENT_VERSION: string = pkg.version;
/**
 * Identifies this agent to the upstream. crates.io refuses a request without a User-Agent and asks
 * that it say who is calling and where to reach them, so the repository from package.json goes in:
 * a fork that changes `repository` there changes this header with it.
 */
const contact = pkg.repository?.url?.replace(/\.git$/, "");
export const USER_AGENT = contact
  ? `${pkg.name}/${pkg.version} (${contact})`
  : `${pkg.name}/${pkg.version}`;
