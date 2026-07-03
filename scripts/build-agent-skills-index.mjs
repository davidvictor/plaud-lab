#!/usr/bin/env node

import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, "..");
const skillName = "plaud-transcript-export";
const skillPackageRoot = join(repoRoot, "skills", skillName);
const wellKnownRoot = join(repoRoot, ".well-known", "agent-skills");
const wellKnownSkillRoot = join(wellKnownRoot, skillName);

const files = [
  "SKILL.md",
  "agents/openai.yaml",
  "references/api.md",
  "scripts/export_plaud.py",
];

function unquote(value) {
  return value.replace(/^["']|["']$/g, "");
}

async function readDescription() {
  const skillMd = await readFile(join(skillPackageRoot, "SKILL.md"), "utf8");
  const match = skillMd.match(/^---\n([\s\S]*?)\n---/);
  if (!match) {
    throw new Error("SKILL.md is missing YAML frontmatter.");
  }

  const lines = match[1].split("\n");
  const start = lines.findIndex((line) => line.startsWith("description:"));
  if (start === -1) {
    throw new Error("SKILL.md frontmatter is missing description.");
  }

  const firstValue = lines[start].replace(/^description:\s*/, "");
  if (firstValue && !firstValue.match(/^[>|]/)) {
    return unquote(firstValue.trim());
  }

  const descriptionLines = [];
  for (const line of lines.slice(start + 1)) {
    if (line.match(/^[A-Za-z0-9_-]+:/)) {
      break;
    }
    descriptionLines.push(line);
  }

  const description = descriptionLines
    .map((line) => line.trim())
    .filter(Boolean)
    .join(" ");

  if (!description) {
    throw new Error("SKILL.md description is empty.");
  }

  return description;
}

function normalizeText(content) {
  return content.replace(/[ \t]+$/gm, "").replace(/\n+$/, "\n");
}

async function copySkillFile(file, targetRoot) {
  const source = join(skillPackageRoot, file);
  const target = join(targetRoot, file);
  await mkdir(dirname(target), { recursive: true });
  const content = await readFile(source, "utf8");
  await writeFile(target, normalizeText(content));
}

async function copyWellKnownFiles() {
  await rm(wellKnownSkillRoot, { force: true, recursive: true });

  for (const file of files) {
    await copySkillFile(file, wellKnownSkillRoot);
  }
}

async function writeIndex(description) {
  const index = {
    skills: [
      {
        name: skillName,
        description,
        files,
      },
    ],
  };

  await mkdir(wellKnownRoot, { recursive: true });
  await writeFile(join(wellKnownRoot, "index.json"), `${JSON.stringify(index, null, 2)}\n`);
}

await copyWellKnownFiles();
await writeIndex(await readDescription());

console.log(`Wrote ${basename(wellKnownSkillRoot)} with ${files.length} files.`);
