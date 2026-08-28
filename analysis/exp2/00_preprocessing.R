# Exp 2 preprocessing: raw Empirica export -> tidy CSVs.
#
# Adapted from 00_preprocessing.R (Exp 1). Do NOT point that script at Exp 2 data
# and do not point this one at Exp 1 data -- the schemas differ in ways that fail
# silently
#
#   * PROLIFIC ID. Exp 1 passed it in the URL and read it from
#     `urlParams$participantKey`. Exp 2 collects it via the PlayerCreate form, so
#     it lands in `participantIdentifier`. Reading urlParams here yields all-NA.
#   * PHASES. Exp 2 rounds carry `phase` ∈ {pretest, training}. Only training
#     rounds are reference-game trials; treating all rounds as trials inflates
#     the count and pollutes accuracy.
#   * The POST-TEST is not a round at all. It runs as an exit step, so its data
#     lives on the player scope in `posttestResponses`.
#   * BLOCKS ARE 12 TRIALS, not 16 (4x4 crossing minus the held-out diagonal).
#
# Outputs, per run folder:
#   games.csv               one row per game, incl. stimulus set + rotation
#   players.csv             one row per player, incl. exit survey + completion flags
#   rounds.csv              TRAINING rounds only, one row per trial
#   chats.csv               one row per message
#   descriptions.csv        pre + post free descriptions, one row per item
#   trial_timing.csv        S6.6 instrumentation, one row per training trial

library(tidyverse)
library(here)
library(jsonlite)

# Overridable so scripts/ingest_exports.py can preprocess each new export folder
# without editing this file:  Rscript -e 'target_experiment_name <- "exp2_..."; source(...)'
if (!exists("target_experiment_name")) target_experiment_name <- "pilot_v1"

# Data is organised by experiment: data/{raw,processed}_data/exp_2/<run>
experiment_folder <- "exp_2"

raw_folder <- here("data/raw_data", experiment_folder, target_experiment_name)
processed_folder <- here("data/processed_data", experiment_folder, target_experiment_name)
dir.create(processed_folder, recursive = TRUE, showWarnings = FALSE)

d_game_raw   <- read_csv(here(raw_folder, "game.csv"), show_col_types = FALSE)
d_player_raw <- read_csv(here(raw_folder, "player.csv"), show_col_types = FALSE)
d_round_raw  <- read_csv(here(raw_folder, "round.csv"), show_col_types = FALSE)
d_stage_raw  <- read_csv(here(raw_folder, "stage.csv"), show_col_types = FALSE)
d_pround_raw <- read_csv(here(raw_folder, "playerRound.csv"), show_col_types = FALSE)

# helper: parse a JSON column that may be NA, returning an empty tibble instead
# of erroring, so one malformed row cannot kill the run
parse_json_col <- function(x) {
  map(x, function(s) {
    if (is.na(s) || s == "") return(NULL)
    tryCatch(fromJSON(s), error = function(e) NULL)
  })
}

# Empirica only emits a column once some player/game has actually set that
# attribute, so an export taken before anyone finishes has no `completedStudy`
# column at all and preprocessing dies on the select(). That is not an edge
# case -- the workflow is to export often and pay promptly, so mid-wave exports
# are normal.
#
# any_of() would paper over it, but silently: the column would vanish and
# coverage would read zero completed dyads with no error. Instead materialise
# the column with the value it logically has when nobody has reached that state,
# so the schema is identical no matter when the export was taken.
ensure_cols <- function(df, defaults, what) {
  missing <- setdiff(names(defaults), names(df))
  for (nm in missing) df[[nm]] <- defaults[[nm]]
  if (length(missing)) {
    message("  note: ", what, " export has no ", paste(missing, collapse = ", "),
            " column(s) -- defaulted (nobody reached that state yet)")
  }
  df
}

d_player_raw <- ensure_cols(d_player_raw, list(
  completedStudy = FALSE, finishedTraining = FALSE, ended = NA_character_,
  intro = NA, introDone = FALSE,
  pretestItemGap = NA, posttestItemGap = NA,
  # Phase-handoff stamps (client, added 2026-08). Absent from every export taken
  # before that build, so they must be defaulted or the select() below dies on
  # older waves.
  pretestCardShownAt = NA_real_, pretestStartedAt = NA_real_,
  pretestSubmittedAt = NA_real_, trainingStartedAt = NA_real_,
  bonus = NA_real_, score = NA_real_, exitSurvey = NA_character_,
  exitStepDone = FALSE, aiUse = NA_character_, aiAgreement = NA_character_
), "player")

# Descriptive treatment config only. setId/setReplicate/compSetId are
# deliberately NOT defaulted: they are analysis identity, and a silently
# NA-filled setId would corrupt the S4.8 coverage tally rather than fail loudly.
d_game_raw <- ensure_cols(d_game_raw, list(
  endedInactive = FALSE,
  describeSecondsPerItem = NA_real_,
  numPretestItems = NA_integer_, numPosttestItems = NA_integer_,
  stimulusSchemaVersion = NA_character_, trainingLabels = NA_character_
), "game")

# ---- games ----------------------------------------------------------------
# setId / setReplicate are what make the S4.8 between-dyad comparison possible:
# two dyads per condition per stimulus set. rotation is now derived from setId,
# so every dyad on a set sees an identical display.
d_game <- d_game_raw |>
  select(gameID = id, batchID, contextStructure, contextSize, status,
         setId, setIndex, setReplicate, setSlotInReplicate, compSetId,
         rotation, numPretestItems, numPosttestItems, describeSecondsPerItem,
         stimulusSchemaVersion, trainingLabels, endedInactive,
         any_of(c("trainingRoundsCompleted", "trainingRoundsExpected", "endedReason")))

# ---- players --------------------------------------------------------------
d_players <- d_player_raw |>
  select(playerID = id, gameID, prolificID = participantIdentifier,
         bonus, score, role, rotation,
         completedStudy, finishedTraining, ended,
         pretestItemGap, posttestItemGap,
         pretestCardShownAt, pretestStartedAt, pretestSubmittedAt,
         trainingStartedAt,
         any_of(c("roundsInactive", "exitStepDone"))) |>
  # Where a player stopped, as a single categorical rather than four timestamps
  # to eyeball. `entered_training` is the normal case; everything before it is a
  # player who never reached a trial, which in the pilot was 2 of 6 timeouts and
  # was indistinguishable from mid-training attrition in the export.
  mutate(
    handoff_stage = case_when(
      !is.na(trainingStartedAt)  ~ "entered_training",
      !is.na(pretestSubmittedAt) ~ "stuck_at_handoff",
      !is.na(pretestStartedAt)   ~ "stuck_in_pretest",
      !is.na(pretestCardShownAt) ~ "stuck_on_pretest_card",
      TRUE                       ~ "never_reached_pretest"
    ),
  ) |>
  # Transition cost has to be measured from when the stage could actually
  # advance, not from when THIS player submitted. The describe stage waits for
  # BOTH partners, so the faster player's "handoff" is dominated by waiting --
  # 46s vs 0.1s for the two players of a smoke-test dyad who both transitioned
  # instantly. Splitting the two keeps a stall visible instead of buried in
  # partner wait.
  group_by(gameID) |>
  mutate(
    pretest_advanced_at = if (all(is.na(pretestSubmittedAt))) NA_real_
                          else max(pretestSubmittedAt, na.rm = TRUE)
  ) |>
  ungroup() |>
  mutate(
    # How long this player sat on "waiting for your partner" (the cost of the
    # lockstep barrier; S4.5 sizes the phase as max(A, B), and this measures it).
    pretest_wait_secs = if_else(
      !is.na(pretest_advanced_at) & !is.na(pretestSubmittedAt),
      (pretest_advanced_at - pretestSubmittedAt) / 1000,
      NA_real_
    ),
    # Actual transition cost: stage release -> first training trial on screen.
    handoff_secs = if_else(
      !is.na(trainingStartedAt) & !is.na(pretest_advanced_at),
      (trainingStartedAt - pretest_advanced_at) / 1000,
      NA_real_
    )
  )

d_players_exit <- d_player_raw |>
  select(playerID = id, exitSurvey) |>
  filter(!is.na(exitSurvey)) |>
  mutate(parsed = parse_json_col(exitSurvey)) |>
  filter(map_lgl(parsed, ~ !is.null(.))) |>
  mutate(parsed = map(parsed, as_tibble)) |>
  select(-exitSurvey) |>
  unnest(parsed)

d_players <- d_players |> left_join(d_players_exit, by = "playerID")

# ---- AI disclosure --------------------------------------------------------
# Self-reported use of an AI assistant, collected in the exit steps. This is a
# DATA-USABILITY flag, not a compliance one: participants are told plainly that
# their answer cannot affect payment, precisely so the answer is honest.
#
#   ai_used   none | some | most | other_help | NA (never asked / didn't answer)
#   ai_tool   free text, optional -- for reference only, not an analysis variable
#
# Analyses of the description DVs should decide explicitly what to do with
# ai_used != "none"; NA means the question was never reached (e.g. a lobby
# case), which is NOT the same as a denial.
d_ai <- d_player_raw |>
  select(playerID = id, aiUse, aiAgreement) |>
  mutate(parsed = parse_json_col(aiUse),
         ai_agreed = !is.na(aiAgreement)) |>
  mutate(
    ai_used  = map_chr(parsed, ~ if (is.null(.x$used)) NA_character_ else as.character(.x$used)),
    ai_tool  = map_chr(parsed, ~ if (is.null(.x$tool)) NA_character_ else as.character(.x$tool))
  ) |>
  select(playerID, ai_used, ai_tool, ai_agreed)

d_players <- d_players |> left_join(d_ai, by = "playerID")

if (any(!is.na(d_players$ai_used))) {
  message("\nAI disclosure:")
  d_players |> count(ai_used) |>
    mutate(line = sprintf("  %-12s %d", coalesce(ai_used, "(not asked)"), n)) |>
    pull(line) |> walk(message)
}

# ---- rounds: TRAINING ONLY ------------------------------------------------
d_round <- d_round_raw |>
  filter(phase == "training") |>
  select(roundID = id, gameID, phase, trialNum, repNum, targetNum,
         numTrials, numTrialsPerBlock, setId,
         target, targetLabel, tangramURLs, displayLabels,
         response, correct, selection, director, matcher,
         selectionMadeAt, clickBlockedAt) |>
  mutate(block = repNum + 1)

# ---- chat -----------------------------------------------------------------
d_chat <- d_round_raw |>
  filter(phase == "training", !is.na(chat)) |>
  select(roundID = id, gameID, trialNum, chat, chatTimestamps, director) |>
  mutate(parsed = parse_json_col(chat)) |>
  filter(map_lgl(parsed, ~ !is.null(.))) |>
  mutate(parsed = map(parsed, as_tibble)) |>
  select(-chat) |>
  unnest(parsed) |>
  unnest(sender, names_sep = "_") |>
  mutate(playerID = sender_id,
         director_msg = (playerID == director)) |>
  select(roundID, gameID, trialNum, playerID, text, director_msg)

# ---- descriptions: the primary DV -----------------------------------------
# Pre and post are the SAME 20 images (S4.4), so pre->post distance is a
# within-item within-person change score. noncomp pre-test is 8 items, not 20
# (S4.6) -- do not treat a short pre-test as missing data.
# Only used when a wave produced no descriptions at all (e.g. a server smoke
# test). Column order matches the real path so downstream code sees one schema.
EMPTY_DESCRIPTIONS <- tibble(
  playerID = character(), gameID = character(), contextStructure = character(),
  setId = integer(), setReplicate = integer(), phase = character(),
  order = integer(), image = character(), label = character(),
  cell = character(), top = character(), bottom = character(),
  text = character(), shownAt = numeric(), submittedAt = numeric(),
  rt_sec = numeric()
)

extract_descriptions <- function(df, col, phase_label) {
  # A wave where nobody submitted a description has no such column at all, and
  # even when it exists the unnested rows carry submittedAt only for items that
  # were actually answered. Return a correctly-typed empty frame rather than
  # letting bind_rows see a zero-column tibble.
  if (!col %in% names(df)) {
    message("  note: no ", col, " column -- no ", phase_label, " descriptions")
    return(NULL)
  }
  out <- df |>
    select(playerID = id, gameID, all_of(col)) |>
    mutate(parsed = parse_json_col(.data[[col]])) |>
    filter(map_lgl(parsed, ~ !is.null(.) && length(.) > 0)) |>
    mutate(parsed = map(parsed, as_tibble)) |>
    select(playerID, gameID, parsed)
  if (nrow(out) == 0) {
    message("  note: no ", phase_label, " descriptions submitted")
    return(NULL)
  }
  out |>
    unnest(parsed) |>
    ensure_cols(list(shownAt = NA_real_, submittedAt = NA_real_),
                paste(phase_label, "descriptions")) |>
    mutate(phase = phase_label,
           rt_sec = (submittedAt - shownAt) / 1000)
}

# NULL parts are dropped rather than bound as typed empty frames: the JSON
# parser infers `top`/`bottom` types from whatever a given export happens to
# contain, so a declared empty frame can collide with a real one on type. Binding
# only the non-empty sides leaves the normal two-phase path byte-identical.
d_desc_parts <- compact(list(
  extract_descriptions(d_player_raw, "pretestResponses",  "pretest"),
  extract_descriptions(d_player_raw, "posttestResponses", "posttest")
))

d_descriptions <- if (length(d_desc_parts) == 0) EMPTY_DESCRIPTIONS else {
  bind_rows(d_desc_parts) |>
    left_join(d_game |> select(gameID, contextStructure, setId, setReplicate),
              by = "gameID") |>
    select(playerID, gameID, contextStructure, setId, setReplicate, phase,
           order, image, label, cell, top, bottom, text,
           shownAt, submittedAt, rt_sec, any_of("autoSubmitted"))
}

# ---- trial timing (S6.6 instrumentation) ----------------------------------
# Decomposes trial time into render -> first message -> selection, which round
# start/end alone cannot do. See S6.7 for what this was built to diagnose.
d_stage_sel <- d_stage_raw |>
  filter(name == "selection") |>
  select(roundID, stage_started = startedLastChangedAt, stage_ended = endedLastChangedAt)

d_rendered <- d_pround_raw |>
  filter(!is.na(renderedAt)) |>
  select(roundID, playerID, renderedAt)

d_trial_timing <- d_round |>
  select(roundID, gameID, trialNum, block, selectionMadeAt, correct) |>
  left_join(d_stage_sel, by = "roundID") |>
  left_join(d_rendered, by = "roundID", relationship = "many-to-many")

# ---- write ----------------------------------------------------------------
write_csv(d_game,          file.path(processed_folder, "games.csv"))
write_csv(d_players,       file.path(processed_folder, "players.csv"))
write_csv(d_round,         file.path(processed_folder, "rounds.csv"))
write_csv(d_chat,          file.path(processed_folder, "chats.csv"))
write_csv(d_descriptions,  file.path(processed_folder, "descriptions.csv"))
write_csv(d_trial_timing,  file.path(processed_folder, "trial_timing.csv"))

# ---- sanity checks ---------------------------------------------------------
# These encode the design's invariants. If one fails, something upstream changed.
message("\n--- ", target_experiment_name, " ---")
message("games: ", nrow(d_game), "  players: ", nrow(d_players),
        "  training rounds: ", nrow(d_round))
message("conditions: ", paste(names(table(d_game$contextStructure)),
                              table(d_game$contextStructure), collapse = ", "))
message("descriptions: ", nrow(d_descriptions),
        " (", sum(d_descriptions$phase == "pretest"), " pre / ",
        sum(d_descriptions$phase == "posttest"), " post)")

message("\nset allocation (should be <= 2 dyads per condition per set at replicate 0):")
d_game |> count(contextStructure, setId, setReplicate) |> print(n = 30)

message("\nrotation should be constant within a set:")
d_game |> group_by(setId) |> summarise(rotations = n_distinct(rotation), .groups = "drop") |>
  filter(rotations > 1) |>
  (\(x) if (nrow(x) == 0) message("  OK - one rotation per set") else print(x))()

message("\npre-test item counts by condition (noncomp should be 8, comp 20):")
d_descriptions |> filter(phase == "pretest") |>
  count(contextStructure, playerID) |> count(contextStructure, n) |> print()

if ("autoSubmitted" %in% names(d_descriptions)) {
  message("\nautoSubmitted rate (high => secondsPerItem too tight): ",
          round(100 * mean(d_descriptions$autoSubmitted, na.rm = TRUE), 1), "%")
}

# ---- payments -------------------------------------------------------------
# One table, one question per row: what do I do with this person?
#
# Payment turns on ONE fact: did they reach an exit screen, and therefore a
# Prolific submission code? Every exit route shows one -- after the post-test,
# after a broken game, and after a lobby timeout -- so "submitted on Prolific"
# does NOT by itself mean "completed the study".
#
#   code    reached an exit code. Approve on Prolific (that pays base) and
#           paste any bonus. Bonus may legitimately be $0.
#   nogame  never got into a game. Flat lobby payment; they did the intro and
#           waited, which is all we asked of them.
#   nocode  in a game, never reached an exit screen. Nothing to approve, so
#           nothing happens automatically -- look at these by hand.

BASE_PAY  <- 11.00  # full study compensation, paid by APPROVING on Prolific
LOBBY_PAY <- 2.50   # reached a lobby and waited
NOLOBBY_PAY <- 1.00 # got through some intro, turned away before a lobby
APPROVE_MINUTES <- 25   # your rule of thumb: longer than this, just approve

# Time in study = first to last attribute write. Empirica stamps every attribute
# with <key>LastChangedAt, so this needs no extra instrumentation.
# Games that ever ran a round. A game with no rounds never left the lobby.
started_games <- unique(d_round_raw$gameID[!is.na(d_round_raw$gameID)])

ts_cols <- names(d_player_raw)[str_detect(names(d_player_raw), "LastChangedAt$")]
d_span <- d_player_raw |>
  select(playerID = id, all_of(ts_cols)) |>
  pivot_longer(-playerID, values_to = "ts", values_transform = as.character) |>
  filter(!is.na(ts), ts != "") |>
  group_by(playerID) |>
  summarise(minutes = as.numeric(difftime(max(ymd_hms(ts)), min(ymd_hms(ts)),
                                          units = "mins")), .groups = "drop") |>
  mutate(minutes = round(minutes, 1))

# A wave where nobody reached the post-test pivots to no `posttest` column at
# all, so name both explicitly rather than trusting what happens to be present.
# Any evidence at all that this person did something. Deliberately broad: the
# consequence of a false negative is docking someone $8.50 for work they did, so
# every channel counts -- a matcher who only ever clicked, a director who only
# ever typed, someone who wrote one pre-test description and then dropped.
d_did_chat <- d_chat |> distinct(playerID) |> mutate(sent_message = TRUE)

d_did_select <- d_round |>
  filter(!is.na(selection), selection != "") |>
  distinct(playerID = matcher) |>
  filter(!is.na(playerID)) |>
  mutate(made_selection = TRUE)

d_desc_text <- d_descriptions |>
  filter(!is.na(text), str_trim(text) != "") |>
  distinct(playerID) |>
  mutate(wrote_text = TRUE)

d_desc_counts <- d_descriptions |>
  count(playerID, phase) |>
  pivot_wider(names_from = phase, values_from = n, values_fill = 0) |>
  ensure_cols(list(pretest = 0L, posttest = 0L), "descriptions")

# paid.log is a backstop against pasting the same list twice, not a source of
# truth: Prolific is the only authority on what actually landed. A row here
# means "decided to pay", which is why it is a column to eyeball rather than a
# filter that silently drops people.
paid_log <- here("data", "paid.log")
d_paid <- if (file.exists(paid_log)) {
  read_csv(paid_log, comment = "#", show_col_types = FALSE,
           col_names = c("prolificID", "category", "amount", "date")) |>
    # Keyed on the ID ALONE, not (ID, category). A participant falls in exactly
    # one tier per wave, so the category adds nothing to the key -- but it makes
    # the ledger fragile: renaming a tier orphans every existing row and re-lists
    # people who were already paid. Normalise the @email.prolific.com form too,
    # or the same person recorded either way looks like two people.
    transmute(prolificID = str_split_i(prolificID, "@", 1)) |>
    distinct() |>
    mutate(already_paid = TRUE)
} else tibble(prolificID = character(), already_paid = logical())

# exitSurvey is consumed by the exit-survey unnest above, so read the code
# evidence straight off the raw frame rather than the joined one.
d_saw_intro <- d_player_raw |>
  transmute(playerID = id,
            saw_intro = !is.na(intro),
            # Finished the instructions+quiz. Distinguishes someone who was
            # waiting on us from someone who wandered off partway through.
            introDone = coalesce(as.logical(introDone), FALSE))

d_code <- d_player_raw |>
  transmute(playerID = id,
            has_code = coalesce(completedStudy, FALSE) |
                       !is.na(exitSurvey) |
                       coalesce(exitStepDone, FALSE))

d_payments <- d_players |>
  left_join(d_span, by = "playerID") |>
  left_join(d_code, by = "playerID") |>
  left_join(d_saw_intro, by = "playerID") |>
  left_join(d_game |> select(gameID, contextStructure), by = "gameID") |>
  left_join(d_desc_counts, by = "playerID") |>
  left_join(d_did_chat,   by = "playerID") |>
  left_join(d_did_select, by = "playerID") |>
  left_join(d_desc_text,  by = "playerID") |>
  mutate(
    pretest  = coalesce(pretest, 0L),
    posttest = coalesce(posttest, 0L),
    # Empirica writes the STRING "null" for a player who never joined a game,
    # not a real NA. Testing only for NA silently files every lobby timeout as
    # though they had played.
    no_game = is.na(gameID) | gameID %in% c("", "null", "NA"),
    # "no more games" means Empirica never assigned them to a game at all: they
    # hit the no-games-available page, typically within two minutes and usually
    # before finishing the quiz. That is NOT a lobby timeout and is not owed
    # lobby compensation -- they should be asked to return the submission.
    #
    # A real lobby timeout is someone who WAS assigned, waited for a partner who
    # never came, and spent the full lobby duration doing it. They are paid.
    # FOUR TIERS, by how far into the study they actually got.
    #
    # "no more games" means Empirica never assigned them a game. That splits in
    # two, and the split matters: someone routed to the no-games page at entry
    # saw nothing and is owed nothing, while someone who worked through the
    # consent and quiz before being turned away spent real effort. `intro` is
    # written only once a player enters the intro flow, so its absence is the
    # structural marker for "saw nothing" -- no time threshold to argue about.
    #
    # A lobby wait is different again: they were ASSIGNED, and sat there while
    # the games filled or their partner never came.
    turned_away = no_game & str_detect(coalesce(ended, ""), "no more games"),
    # Tier 3 is "never got out of the lobby", which means THE GAME NEVER
    # STARTED -- not "produced no data". Someone assigned to a game that ran,
    # who then sat inactive through it, was in the task and is paid in full;
    # testing for data would wrongly demote them to lobby compensation.
    # Empirica's own signal, from expiredIndividualLobbyTimeout():
    #
    #   if (!game || game.hasStarted || ...) return;
    #   player.exit("lobby timed out");
    #
    # The guard means this string is only ever written when the game had NOT
    # started, so it provably implies zero data. That makes it authoritative --
    # better than inferring from round counts. ("lobby timed out before reached
    # intro" is the SHARED-lobby variant; unreachable under kind: "individual",
    # but matched here so a config change cannot silently misfile people.)
    lobby_ended = str_detect(coalesce(ended, ""), "lobby timed out"),
    game_started = gameID %in% started_games,
    # Contributed ANYTHING? Someone who sat in a started game and produced
    # nothing at all -- never typed, never clicked, never wrote a description --
    # did not merely fail to finish. They occupied a slot and cost their partner
    # the session, so they are compensated as a lobby case rather than in full.
    contributed = coalesce(wrote_text, FALSE) | coalesce(sent_message, FALSE) |
                  coalesce(made_selection, FALSE) |
                  coalesce(finishedTraining, FALSE) | coalesce(score, 0) > 0,
    # Walked away mid-quiz. `introDone` is never set, so they were never a READY
    # player: introDoneCheck() counts only `introDone && !ended` against
    # playerCount, so they neither block the game from starting nor hold a seat.
    # When the game does start around them, introDoneCheck unassigns them
    # (`plyr.set("gameID", null)`) and reassigns them elsewhere. Nothing ejects
    # them before that and no lobby timer is ever armed, which is why `ended`
    # stays empty -- they are inert, not stuck.
    #
    # NOTE that their gameID can therefore be CLEARED later. Someone who looks
    # like a lobby case in a mid-wave snapshot may be `no_game` in the final
    # export -- one more reason payments run off the export, not a snapshot.
    #
    # Without this they look identical to a genuine lobby timeout (game assigned,
    # no data) and would be paid $2.50 for having abandoned the task. The
    # separator is introDone: someone who finished the quiz and then waited did
    # what we asked; someone who never finished it left of their own accord.
    # A real timeout is exempt regardless -- `ended` proves they waited it out.
    abandoned_intro = !coalesce(lobby_ended, FALSE) &
                      !coalesce(introDone, FALSE) &
                      !contributed,
    group = case_when(
      turned_away & !coalesce(saw_intro, FALSE) ~ "no_intro",   # tier 1
      turned_away                               ~ "no_lobby",   # tier 2
      abandoned_intro                           ~ "abandoned",  # left mid-quiz
      lobby_ended | !game_started | !contributed ~ "lobby",      # tier 3
      TRUE                                      ~ "data"),      # tier 4
    category = case_when(group == "abandoned" ~ "none",
                         group == "no_intro" ~ "none",
                         group == "no_lobby" ~ "no_lobby",
                         group == "lobby"    ~ "lobby",
                         TRUE                ~ "bonus"),
    amount = case_when(group == "abandoned" ~ 0,
                       group == "no_intro" ~ 0,
                       group == "no_lobby" ~ NOLOBBY_PAY,
                       group == "lobby"    ~ LOBBY_PAY,
                       TRUE                ~ coalesce(bonus, 0)),
    action = case_when(
      group == "abandoned" ~ "no payment -- left during the quiz",
      group == "no_intro" ~ "ask to RETURN -- saw nothing, $0",
      group == "no_lobby" ~ sprintf("pay $%.2f, ask to RETURN -- no lobby", NOLOBBY_PAY),
      group == "lobby" & lobby_ended ~ sprintf("pay lobby $%.2f -- no partner", LOBBY_PAY),
      group == "lobby"    ~ sprintf("pay lobby $%.2f -- in a game, contributed nothing", LOBBY_PAY),
      minutes >= APPROVE_MINUTES ~ sprintf("approve ($%.2f) + bonus", BASE_PAY),
      TRUE ~ sprintf("CHECK: has data but only %.0f min -- then approve ($%.2f) + bonus",
                     minutes, BASE_PAY))
  ) |>
  mutate(.pid = str_split_i(prolificID, "@", 1)) |>
  left_join(d_paid, by = c(".pid" = "prolificID")) |>
  select(-.pid) |>
  mutate(already_paid = coalesce(already_paid, FALSE)) |>
  # prolificID then amount, in that order, so the first two columns can be
  # copied straight into Prolific's bulk bonus box ("ID,amount" per line).
  select(prolificID, amount, group, action, minutes, pretest, posttest,
         category, already_paid, contextStructure, gameID) |>
  arrange(group, desc(minutes))

write_csv(d_payments, file.path(processed_folder, "payments.csv"))

# Two paste-ready files: exactly the rows to pay and exactly two columns, with
# NO header, so the whole file can be selected and dropped into Prolific's bulk
# bonus box. payments.csv keeps everything else for troubleshooting.
#
# amount is formatted as a string to keep the trailing zeros -- write_csv turns
# 2.50 into 2.5 and 0.00 into 0, which is legible but not what you want to paste.
# Server-test players ("test0", "test2") reach exit codes exactly like real
# dyads, so without this they land in a paste-ready file and get pasted into
# Prolific, where the ID does not exist. A real Prolific ID is 24 hex chars;
# Prolific sometimes passes it in email form, so match the local part.
is_real_participant <- function(pid) {
  str_detect(str_to_lower(str_split_i(coalesce(pid, ""), "@", 1)),
             "^[0-9a-f]{24}$")
}

paste_ready <- function(df) {
  df |>
    filter(is_real_participant(prolificID)) |>
    # Strip the @email.prolific.com suffix Prolific sometimes sends: the bare
    # ID is what its bulk bonus box accepts.
    transmute(prolificID = str_split_i(prolificID, "@", 1),
              amount = sprintf("%.2f", amount))
}

d_bonus <- d_payments |>
  filter(group == "data", amount > 0, !already_paid) |>
  paste_ready()
d_lobby <- d_payments |>
  filter(group == "lobby", !already_paid) |>
  paste_ready()

# Not a payment list: these people never got into a game and are owed nothing.
# Written out so you can ask them to return the submission rather than hunting
# for them in the full table.
d_nolobby <- d_payments |>
  filter(group == "no_lobby", !already_paid) |>
  paste_ready()

# Not a payment list: tier 1 saw nothing at all and is owed nothing.
d_returns <- d_payments |>
  filter(group == "no_intro") |>
  filter(is_real_participant(prolificID)) |>
  transmute(prolificID = str_split_i(prolificID, "@", 1), minutes)

write_csv(d_bonus, file.path(processed_folder, "bonus.csv"), col_names = FALSE)
write_csv(d_lobby, file.path(processed_folder, "lobby.csv"), col_names = FALSE)
write_csv(d_nolobby, file.path(processed_folder, "turned_away.csv"), col_names = FALSE)
write_csv(d_returns, file.path(processed_folder, "returns.csv"))

message("\npayments: ", nrow(d_payments), " people")
d_payments |>
  count(group, action) |>
  mutate(line = sprintf("  %-7s %-34s %s", group, action, n)) |>
  pull(line) |> walk(message)
message("\npaste straight into Prolific (no header, two columns):")
message(sprintf("  bonus.csv        %2d  $%6.2f   tier 4: gave data -> ALSO approve ($%.2f base each)",
                nrow(d_bonus), sum(as.numeric(d_bonus$amount)), BASE_PAY))
message(sprintf("  lobby.csv        %2d  $%6.2f   tier 3: reached a lobby, waited",
                nrow(d_lobby), sum(as.numeric(d_lobby$amount))))
message(sprintf("  turned_away.csv  %2d  $%6.2f   tier 2: some intro, never reached a lobby",
                nrow(d_nolobby), sum(as.numeric(d_nolobby$amount))))
message("  (all three exclude anyone already in paid.log)")
message(sprintf("\n  returns.csv      %2d      $0.00   tier 1: turned away at entry, saw nothing",
                nrow(d_returns)))
message("                                 ask these to return; nothing to pay")

message("\neverything else, for troubleshooting:")
message("  payments.csv  ", nrow(d_payments), " people, all columns")
message("\nin ", processed_folder)
