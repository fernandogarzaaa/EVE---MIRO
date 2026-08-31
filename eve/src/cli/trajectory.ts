import { parseArgs } from "node:util";
import { validateTrajectory, type TrajectoryInput } from "../cognition/trajectoryPolicy.js";

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString("utf8");
}

/**
 * `eve trajectory --stdin` — read JSON ExperienceCandidate (or observation/
 * prediction/action/outcome) and emit a ValidatedExperience-shaped object
 * using HeuristicCognition (offline).
 */
export async function runTrajectoryCommand(rest: readonly string[]): Promise<number> {
  let values: { stdin?: boolean };
  try {
    const parsed = parseArgs({
      args: [...rest],
      options: { stdin: { type: "boolean" } },
    });
    values = parsed.values as { stdin?: boolean };
  } catch (err) {
    process.stderr.write(`${err instanceof Error ? err.message : String(err)}\n`);
    return 2;
  }

  if (!values.stdin) {
    process.stderr.write("eve trajectory needs --stdin (JSON on standard input).\n");
    return 2;
  }

  let raw: string;
  try {
    raw = await readStdin();
  } catch (err) {
    process.stderr.write(`${err instanceof Error ? err.message : String(err)}\n`);
    return 1;
  }

  let input: TrajectoryInput;
  try {
    input = JSON.parse(raw) as TrajectoryInput;
  } catch (err) {
    process.stderr.write(`Invalid JSON on stdin: ${err instanceof Error ? err.message : String(err)}\n`);
    return 2;
  }

  try {
    const result = await validateTrajectory(input);
    process.stdout.write(`${JSON.stringify(result)}\n`);
    return 0;
  } catch (err) {
    process.stderr.write(
      `eve trajectory failed: ${err instanceof Error ? err.message : String(err)}\n`,
    );
    return 1;
  }
}
