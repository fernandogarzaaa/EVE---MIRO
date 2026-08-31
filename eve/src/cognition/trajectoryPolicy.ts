import { HeuristicCognition } from "./heuristicCognition.js";
import type { CognitiveContext } from "./cognition.js";
import { comparePrediction, predictInteraction } from "./mentalModel.js";
import { clamp01, createRng } from "../core/random.js";
import type { Percept, VisibleElement } from "../core/types.js";
import { EmotionalState } from "../emotion/emotionalState.js";
import { OperatorMemory } from "../memory/memory.js";
import { getPersona } from "../personas/library.js";
import { createGoal, GoalStack } from "../planning/goals.js";

export interface TrajectoryInput {
  id?: string;
  observation?: unknown;
  prediction?: unknown;
  action?: unknown;
  outcome?: unknown;
  context?: Record<string, unknown>;
  layer?: string;
  candidate?: Record<string, unknown>;
  episode_id?: string;
}

export interface ValidatedExperienceShape {
  id: string;
  validity: number;
  confidence: number;
  prediction_error: number | null;
  learning_value: number;
  transferability: number;
  retention_score: number;
  counterfactuals: Array<{
    id: string;
    base_experience_id: string;
    intervention: string;
    predicted_delta: Record<string, number>;
    label: "model-generated";
    fact: false;
  }>;
  applicability: string[];
  artifact?: Record<string, unknown>;
  layer: string;
}

function textOf(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function hashSeed(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function makeElement(id: number, text: string, role: VisibleElement["role"]): VisibleElement {
  return {
    id,
    role,
    text,
    box: { x: 10, y: 10 + id * 40, width: 220, height: 32 },
    interactive: role === "button" || role === "textbox",
    disabled: false,
    editable: role === "textbox",
    focused: false,
    clippedByViewport: false,
  };
}

function makePercept(title: string, body: string, actionLabel: string): Percept {
  return {
    timestamp: 0,
    url: "eve://trajectory",
    title,
    viewport: { width: 800, height: 600 },
    scrollY: 0,
    scrollHeight: 600,
    screenshot: null,
    elements: [
      makeElement(1, title, "heading"),
      makeElement(2, body.slice(0, 400), "text"),
      makeElement(3, actionLabel || "continue", "button"),
    ],
    dialogs: [],
    loadingIndicator: false,
  };
}

/**
 * Offline experience validation using HeuristicCognition + mentalModel.
 * Mapping a full web percept would be forced; this still uses EVE types.
 */
export async function validateTrajectory(raw: TrajectoryInput): Promise<ValidatedExperienceShape> {
  const nested = raw.candidate && typeof raw.candidate === "object" ? raw.candidate : undefined;
  const src = (nested ?? raw) as TrajectoryInput;
  const observation = src.observation ?? raw.observation;
  const prediction = src.prediction ?? raw.prediction;
  const action = src.action ?? raw.action;
  const outcome = src.outcome ?? raw.outcome;
  const layer = String(src.layer ?? raw.layer ?? "agent");
  const id = String(src.id ?? raw.id ?? "exp_trajectory");
  const actionLabel = textOf(action) || "act";
  const obsText = textOf(observation);
  const predText = textOf(prediction);
  const outcomeText = textOf(outcome);

  const persona = getPersona("first-time-user");
  const rng = createRng(hashSeed(id));
  const emotion = new EmotionalState(persona);
  const memory = new OperatorMemory(persona, rng);
  const goals = new GoalStack(createGoal(actionLabel || "validate this experience"));
  const policy = new HeuristicCognition("goal-directed");

  const before = makePercept("experience", predText || obsText || actionLabel, actionLabel);
  const ctx: CognitiveContext = {
    percept: before,
    previousPercept: null,
    persona,
    emotion: emotion.snapshot(),
    memory,
    goals,
    rng,
    step: 1,
    elapsedMs: 0,
  };
  const decision = await policy.decide(ctx);

  const target = before.elements.find((el) => el.interactive) ?? before.elements[0]!;
  const predicted = predictInteraction(
    target,
    "click",
    clamp01(0.3 + persona.traits.techLiteracy * 0.4 + emotion.snapshot().confidence * 0.3),
  );
  const after = makePercept("outcome", outcomeText || obsText, actionLabel);
  const compared = comparePrediction(predicted, before, after, 200);

  const confidence = clamp01(decision.prediction.confidence * (1 - compared.surprise * 0.5));
  const predictionError = compared.surprise;
  const validity = clamp01(1 - compared.surprise);
  const learningValue = clamp01(compared.surprise * 0.5 + decision.effort * 0.5);

  return {
    id,
    validity,
    confidence,
    prediction_error: predictionError,
    learning_value: learningValue,
    transferability: clamp01(0.5 + persona.traits.learningRate * 0.2),
    retention_score: clamp01(persona.traits.memoryRetention),
    counterfactuals: [
      {
        id: `cf_${id}_alt`,
        base_experience_id: id,
        intervention: `model-generated alternative to ${actionLabel}`,
        predicted_delta: { surprise: -compared.surprise * 0.3 },
        label: "model-generated",
        fact: false,
      },
    ],
    applicability: ["simulated", layer],
    artifact: {
      experience: decision.rationale,
      conditions: [actionLabel, outcomeText.slice(0, 80)].filter(Boolean),
      confidence,
      source: [id],
      provenance_kind: "simulated",
      policy: policy.name,
    },
    layer,
  };
}
