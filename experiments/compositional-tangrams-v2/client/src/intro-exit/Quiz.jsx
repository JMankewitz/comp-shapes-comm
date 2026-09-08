import React, { useState } from "react";
import { InstructionsBody } from "./InstructionsBody";
import { Button } from "../components/Button";

export function Quiz({ next }) {
  const [answers, setAnswers] = useState({});
  const [showInstructions, setShowInstructions] = useState(false);

  // Your existing questions array
  const questions = [
    {
      question: "The director can click on a color to end the round:",
      choices: [
        "True",
        "False",
      ],
      correctAnswer: "False",
    },
    {
      question: "The matcher wants to click on the target that...",
      choices: [
        "(A) the director is describing",
        "(B) looks most familiar",
      ],
      correctAnswer: "(A) the director is describing",
    },
{
      question: "The target object is marked for the director with...",
      choices: [
        "(A) a black box",
        "(B) a red triangle",
        "(C) a highlighted background",
      ],
      correctAnswer: "(A) a black box",
    },
    {
      question: "Only the director can send messages ",
      choices: [
        "True",
        "False",
      ],
      correctAnswer: "False",
    },
    {
        question: "At the end of each round... ",
        choices: [
          "(A) all shapes are shuffled",
          "(B) all shapes stay in the same location",
        ],
        correctAnswer: "(A) all shapes are shuffled",
      },
      {
        question: "The locations of the 4 objects are the same for the director and the matcher",
        choices: [
          "True",
          "False",
        ],
        correctAnswer: "False",
      },
        // Not a mechanics question. The quiz is the only screen a participant
        // CANNOT skip, so it is the one place this fact is guaranteed to land.
        // In the pilot, 24 of 25 partial sessions ended because one person left
        // and took their partner's completed work with them -- the answer below
        // is literally what happens (Empirica ends the game for both, and
        // neither can be re-paired). Stated in Introduction.jsx so it is
        // answerable rather than a trick.
        {
          question: "If you stop partway through the game, what happens to your partner?",
          choices: [
            "(A) They are automatically matched with someone else",
            "(B) Their session ends too, and the work they have done is lost",
            "(C) Nothing - they finish the study on their own",
          ],
          correctAnswer: "(B) Their session ends too, and the work they have done is lost",
        },
  ];

  const handleChoiceChange = (questionIndex, event) => {
    setAnswers({
      ...answers,
      [questionIndex]: event.target.value,
    });
  };

  const handleSubmit = (event) => {
    event.preventDefault();

    const allCorrect = questions.every(
      (q, index) => answers[index] === q.correctAnswer
    );

    if (allCorrect) {
      alert("Congratulations, you answered all questions correctly!");
      next();
    } else {
      alert("Some answers are incorrect. Please try again.");
    }
  };

  // If showing instructions, render the instructions view
  if (showInstructions) {
    return (
      <div className="mt-3 sm:mt-5 p-20">
        <h3 className="text-lg leading-6 font-medium text-gray-1000">
          Task Instructions
        </h3>
        <h2>Matching Game</h2>
        <InstructionsBody />
        <Button 
          handleClick={() => {
            setShowInstructions(false);
          }}
        >
          Return to Quiz
        </Button>
      </div>
    );
  }

  // Quiz view
  return (
    <div className="flex items-center justify-center w-screen" style={{ margin: "50px" }}>
      <div className="w-1/2">
        <h3 className="text-lg leading-6 text-gray-900">
          <center>Comprehension Quiz</center>
        </h3>
        <br />
        <form>
          {questions.map((q, questionIndex) => (
            <div key={questionIndex}>
              <br />
              <h2><b>{q.question}</b></h2>
              <br />
              {q.choices.map((choice, index) => (
                <label key={index} style={{ display: "block", margin: "8px 0" }}>
                  <input
                    type="radio"
                    style={{ marginRight: "10px" }}
                    name={`question-${questionIndex}`}
                    value={choice}
                    checked={answers[questionIndex] === choice}
                    onChange={(e) => handleChoiceChange(questionIndex, e)}
                  />
                  {choice}
                </label>
              ))}
            </div>
          ))}
          <br />
          <div className="flex justify-between">
            <Button 
              handleClick={(e) => {
                e.preventDefault();
                setAnswers({});
                setShowInstructions(true);
              }}
              primary
            >
              Review Instructions
            </Button>
            <Button handleClick={handleSubmit}>
              Submit
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}