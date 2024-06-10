import React from "react";
import { Button } from "../components/Button";

export function Introduction({ next }) {
  return (
    <div className="mt-3 sm:mt-5 p-20">
      <h3 className="text-lg leading-6 font-medium text-gray-1000">
        Task Instructions
      </h3>
      <h2>Matching Game  </h2>
      <div className="mt-3 mb-6" width="800px">
        <p className="text-md text-gray-900">
        In this experiment you will play a fun matching game with another turker! Both of you are going to be given a set of tangram pictures which will look like this. 
        </p>
        <br></br>
        <p>
          <center><img width="300px" src="./tangrams.png" alt="Example gameplay" /></center>
        </p>
        <br></br>
        <p>
        You'll each see the same 4 images but they will be scrambled into different locations.
      </p>
      <br></br>

      <p>
    On each round, one of you will be assigned the <b> Director </b> role and the
    other will be the <b> Matcher</b>. On each round, the director is
    shown a <b>black box</b> marking one of the four objects as the
    target (see image below). Only the director can see which object
    is the target. The task of the director is to tell the matcher
    which one of the objects is the target. The matcher in turn needs
    to select the right object based on this information. You'll both
    get <b> a bonus of $0.01 for each correct response</b>, so pay
    attention! Remember that it doesn't make sense to describe the
    location of the target object, since the order of the images is
    different for the director and the matcher.
</p>
<br></br>
<p>
          <center><img width="600px" src="./tangramBoard.png" alt="Example gameplay" /></center>
        </p>
<p>
      <i> <center> <small> Only the director can see the black square around the target object. </small> </center> </i>
    </p>
    <br></br>
    <p>
  The goal is for the matcher to identify the correct shape
  based on what the director has said. In order to communicate,
  you're given a chatbox where you can send messages back and forth
  to each other. The director can say whatever they need to indicate
  which object is the target (this isn't a game of "taboo"!), and the
  matcher can respond or ask questions at any point. Some rounds
  will be easier and some will be harder. </p>
  <br></br>
<p> Once the matcher clicks on the object they believe is the target,
  based on conversation through the chat box, both players will be
  given feedback (the director will see what the matcher clicked, and
  the matcher will see the true target), and you will both be
  automatically forwarded to the next round of objects. There are a
  total of <b>64 rounds</b> with many of the same sets of objects, so each one
  will be the target several times. After the final round you will
  fill out a quick 15 second survey and be on your way.
</p>
<br></br>
<p> A few final notes: First, since you are playing with another
  prolificer, you may see this screen before the game begins: </p>
  <br></br>
  <p>
          <center><img width="200px" src="./waitScreen.png" alt="Wait Screen" /></center>
        </p>

  <br></br>

  <p>
  Just hold tight. Another player should join the game within the next
  few minutes. If you're in the waiting room 15 minutes without
  another player joining, your game will automatically be submitted and
  accepted, out of gratitude for the time you spent waiting.
</p>
<br></br>
<p>
  Second, please be respectful of the player you're playing with: do
  not send inappropriate material through the chat box (including
  screenshots of the shape you're trying to refer to), and try to be
  as responsive as possible.
</p>
<br></br>
<p> Finally, please DO NOT refresh the page at any point once you
start the game (including the waiting page). If you refresh, you will
not be able to rejoin the game you were in and you and your partner
may not be able to submit the game. Thank you!
</p>
<br></br>
<p> Next, there will be a short quiz to test your understanding of the rules of the game. Once you pass the quiz, you will be allowed to match with another player!
</p>


      </div>

      <Button handleClick={next} autoFocus>
        <p>Next</p>
      </Button>
    </div>
  );
}
