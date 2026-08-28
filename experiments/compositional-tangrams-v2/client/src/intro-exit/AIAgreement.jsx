import React, { useState } from "react";
import { usePlayer } from "@empirica/core/player/classic/react";
import { Button } from "../components/Button";

// Shown immediately after the consent, as part of the same act: saying what we
// need from participants and what they are contributing, before they invest any
// effort. It reads as a compliance gate if placed after the quiz.
//
// Note this comes BEFORE the instructions, so it cannot assume the participant
// knows what the task is -- it has to say enough about the study to make the ask
// make sense.
//
// The ask is framed as WHY rather than as a rule. This study measures how people
// describe shapes to each other; a description written by a language model is
// not evidence about human reference, so an assisted response is not a rule
// violation so much as unusable data. Participants who understand that are more
// likely to comply, and more likely to disclose honestly at the end (see
// AIDisclosure).
//
// Deliberately NOT a threat: no mention of rejection or withheld payment.
// Telling people their pay is at risk is what produces false denials at the exit
// survey, which is the one thing that would make the disclosure worthless.
export function AIAgreement({ next }) {
  const player = usePlayer();
  const [agreed, setAgreed] = useState(false);

  function handleSubmit(event) {
    event.preventDefault();
    if (!agreed) return;
    player.set("aiAgreement", { agreed: true, at: Date.now() });
    next();
  }

  return (
    <div className="py-8 max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
      <h3 className="text-lg font-semibold leading-6 text-gray-900">
        What we are asking of you
      </h3>

      <div className="mt-4 space-y-4 text-gray-700">
        <p>
          Thank you for agreeing to take part. Before we begin, here is what this
          study needs from you and why.
        </p>
        <p>
          We are researchers studying{" "}
          <strong>how people describe things to each other</strong>. In this study
          you will look at abstract shapes and put them into words — first on your
          own, then with a partner you are matched with. What we are measuring is
          how people do that: how you see a shape, how you describe it, and how you
          and your partner come to understand each other over time.
        </p>
        <p>
          That means we are interested in <strong>your</strong> description, however
          rough, uncertain, or strange it feels. There are no wrong answers. A messy
          human description is exactly the data we need.
        </p>
        <p>
          For this reason, please do not use ChatGPT, Claude, Gemini, or any other
          AI assistant to write your descriptions or your messages to your partner.
          A description written by an AI tells us nothing about how people
          communicate, so we cannot use it in our research — even if it is a very
          good description.
        </p>
        <p className="text-sm text-gray-500">
          At the end we will ask whether you used any AI tools. Answering honestly
          will not affect your payment in any way. We simply need to know which
          responses we can include in our analysis.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="mt-6">
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            className="mt-1 h-4 w-4"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
          />
          <span className="text-gray-900">
            I agree to write my own descriptions and messages, without help from an
            AI assistant.
          </span>
        </label>
        <div className="mt-6">
          <Button type="submit" disabled={!agreed}>
            Continue
          </Button>
        </div>
      </form>
    </div>
  );
}
