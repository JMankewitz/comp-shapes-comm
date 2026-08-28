import React, { useState } from "react";
import { usePlayer } from "@empirica/core/player/classic/react";
import { Button } from "../components/Button";

// Asked in the exit steps, before the demographic survey.
//
// The design goal is an HONEST answer, not a low one. Every piece of copy here
// is chosen to remove the incentive to deny: payment is stated as unconditional
// up front (not in fine print at the bottom), the phrasing is non-accusatory,
// and partial use has its own option so someone who used AI once is not forced
// to choose between "no" and a confession that feels total.
//
// A disclosure rate of zero would not be good news -- it would mean the question
// is not working. Compare the rate against the AIAgreement acceptance to sanity
// check it.
const OPTIONS = [
  { value: "none", label: "No — I wrote everything myself" },
  { value: "some", label: "I used an AI tool for a few responses" },
  { value: "most", label: "I used an AI tool for most or all responses" },
  { value: "other_help", label: "I got help from another person (not AI)" },
];

export function AIDisclosure({ next }) {
  const player = usePlayer();
  const [used, setUsed] = useState("");
  const [tool, setTool] = useState("");

  const disclosed = used && used !== "none";

  function handleSubmit(event) {
    event.preventDefault();
    if (!used) return;
    player.set("aiUse", {
      used,
      tool: disclosed ? tool.trim() : "",
      at: Date.now(),
    });
    next();
  }

  return (
    <div className="py-8 max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
      <h3 className="text-lg font-semibold leading-6 text-gray-900">
        One last question: did you use any AI tools?
      </h3>

      <div className="mt-4 space-y-3 text-gray-700">
        <p>
          <strong>
            Your answer will not affect your payment. You will be paid in full
            either way, and this cannot be held against you.
          </strong>{" "}
          We are asking only so we know which responses we can include in our
          analysis of human communication.
        </p>
        <p className="text-sm text-gray-500">
          Please answer honestly — an accurate &ldquo;yes&rdquo; is far more
          useful to us than a &ldquo;no&rdquo;, and there is no penalty of any
          kind.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        <div className="space-y-2">
          {OPTIONS.map((o) => (
            <label key={o.value} className="flex items-center gap-3 cursor-pointer">
              <input
                type="radio"
                name="aiUse"
                value={o.value}
                checked={used === o.value}
                onChange={(e) => setUsed(e.target.value)}
                className="h-4 w-4"
              />
              <span>{o.label}</span>
            </label>
          ))}
        </div>

        {/* Only the tool, and only optionally. Asking WHICH PARTS they used it
            on made the question feel like an audit -- reconstructing where you
            slipped is exactly the kind of effort that pushes someone toward
            answering "no" instead. The categorical answer is what gates data
            usability; the tool name is just useful to know. */}
        {disclosed ? (
          <div className="pl-6 border-l-2 border-gray-200">
            <label className="block text-sm text-gray-700 mb-1">
              Which tool was it? (optional)
            </label>
            <input
              type="text"
              value={tool}
              onChange={(e) => setTool(e.target.value)}
              placeholder="e.g. ChatGPT"
              className="w-64 rounded-md border-gray-300 shadow-sm text-sm"
            />
          </div>
        ) : null}

        <div className="pt-2">
          <Button type="submit" disabled={!used}>
            Continue
          </Button>
        </div>
      </form>
    </div>
  );
}
