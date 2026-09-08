import React from "react";

// THE task instructions, in one place.
//
// This body was duplicated: Introduction.jsx showed one copy and the quiz's
// "Review Instructions" button showed another. The quiz copy silently fell
// behind -- it was missing the three-part structure added for Exp 2 AND the
// live-partner paragraphs, so a participant who clicked through to check an
// answer was reading instructions that no longer described the study, and the
// new partner quiz question was unanswerable from them.
//
// Both callers render this and supply their own heading and button. Edit the
// wording here and it changes in both.
export function InstructionsBody() {
  return (
      <div className="mt-3 mb-6" width="800px">
        <p className="text-md text-gray-900">
        In this experiment you will play a fun matching game with another participant! Both of you are going to be given a set of tangram pictures which will look like this. 
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

      {/* Exp 2: participants now do a solo description phase before and after the
          game. Without this they are dropped into 20 free-text trials with no
          warning. WORDING NEEDS REVIEW before the pilot runs. */}
      <p>
    This study has <b>three parts</b>. In <b>Part 1</b> you will see a series of
    shapes one at a time and type a short description of each one, on your own.
    In <b>Part 2</b> you will play the matching game described below with a
    partner. In <b>Part 3</b> you will describe a set of shapes on your own
    again, the same way you did in Part 1.
      </p>
        <br></br>
        {/* Stated here so the quiz question about it has a source to point back
            to. It is also the single fact most worth landing: in the pilot, 24
            of 25 partial sessions ended because ONE person left, taking their
            partner's completed work with them. */}
        <p>
      <b>You will be playing with a real person, live.</b> Your partner is another
      participant who is online at the same time as you, waiting on you just as
      you wait on them. The game cannot continue without both of you.
        </p>
        <br></br>
        <p>
      This means that <b>if you stop partway through, the session ends for your
      partner too</b>, and the work they have already done is lost. Neither of you
      can be matched with someone else afterwards. Please only continue if you
      can give this your full attention for about 45 minutes. If you cannot,
      please return the study on Prolific now &mdash; there is no penalty, and it
      frees the slot for someone else.
        </p>
      <br></br>
      <p>
    In Parts 1 and 3 there is no partner and no score &mdash; just type how you
    would describe each shape so that another person could pick it out. Your
    bonus comes from Part 2.
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
    get <b> a bonus of $0.03 for each correct response</b>, so pay
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
  total of <b>48 rounds</b> in this part, with the same set of objects recurring,
  so each one will be the target several times. After the final round you will
  move on to <b>Part 3</b>, where you describe shapes on your own again just as
  you did in Part 1, and then a short survey.
</p>
<br></br>
<p> A few final notes: First, since you are playing with another
  prolificer, you may see this screen before the game begins: </p>
  <br></br>
  <p>
          <center><img width="200px" src="./waitScreen.png" alt="Wait Screen" /></center>
        </p>

  <br></br>

  {/* Must match what the exit pages actually do. The old text promised a
      15-minute wait ending in an automatic submit-and-accept; the lobby is
      10 minutes (lobbyConfig "10m individual Kick") and it ends by routing to
      LobbyExitSurvey, which gives NO completion code and asks them to return
      for a $2.50 bonus. Keep this in step with PAY.LOBBY in tiers.js. */}
  <p>
  Just hold tight &mdash; another player should join within a few minutes. If
  nobody becomes available within <b>10 minutes</b>, we will ask you to
  <b> return the study on Prolific</b> and send you a <b>bonus of $2.50</b> for
  the time you spent waiting. Returning does not count against you, there is no
  completion code for that outcome, and you do not need to do anything else.
</p>
<br></br>
<p>
  Second, please be respectful of the player you're playing with: do
  not send inappropriate material through the chat box (including
  screenshots of the shape you're trying to refer to), and try to be
  as responsive as possible.
</p>
<br></br>
{/* "paid in full" is accurate: anyone who produced any data is tier 4 and is
    approved for the base payment plus whatever bonus they earned, however the
    game ended. Fixed "you time" -> "your time" while here. */}
<p> Finally, please refresh the page if your game fails to load or you lose
  connection &mdash; the game will try to reconnect you with your partner. If
  you or your partner disconnect and the session cannot continue, you will
  still be paid in full for the work you have done, plus any bonus you earned.
  You do not need to message us.
</p>
<br></br>
<p> Next, there will be a short quiz to test your understanding of the rules of the game. Once you pass the quiz, you will be allowed to match with another player!
</p>


      </div>
  );
}
