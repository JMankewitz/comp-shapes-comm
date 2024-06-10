import React, { useState } from "react";
import { Button } from "../components/Button";

export function Quiz({next}) {
  //const game = useGame();
  //const treatment = game.get("treatment");
  //const { feedback } = treatment;
  const [answers, setAnswers] = useState({});

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
          "(A) all tangrams are shuffled",
          "(B) all tangrams stay in the same location",
        ],
        correctAnswer: "(A) all tangrams are shuffled",
      },
      {
        question: "The locations of the 4 objects are the same for the director and the matcher",
        choices: [
          "True",
          "False",
        ],
        correctAnswer: "False",
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

  const radioStyle = {
    display: "block",
    margin: "8px 0",
  };

  const inputStyle = {
    marginRight: "10px",
  };

  return (
    <div className="flex items-center justify-center w-screen" style={{ margin: "50px" }}><div className="w-1/2">
       <h3 className="text-lg leading-6 text-gray-900"> <center>
        Comprehension Quiz </center>
      </h3> <br/>
      <form>
        {questions.map((q, questionIndex) => (
          <div key={questionIndex}>
           <br/> <h2><b>{q.question}</b></h2> <br/>
            {q.choices.map((choice, index) => (
              <label key={index} style={radioStyle}>
                <input
                  type="radio"
                  style={inputStyle}
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
        <Button handleClick={handleSubmit}>Submit</Button>
      </form>
    </div> </div>
  );
}