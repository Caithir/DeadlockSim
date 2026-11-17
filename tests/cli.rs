//! Runs the `deadlock-sim` binary the way a user would.

use std::io::Write;
use std::process::{Command, Output, Stdio};

use serde_json::Value;

fn run(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_deadlock-sim")).args(args).output().expect("binary runs")
}

fn ok(args: &[&str]) -> String {
    let out = run(args);
    assert!(out.status.success(), "{args:?} failed: {}", String::from_utf8_lossy(&out.stderr));
    String::from_utf8(out.stdout).unwrap()
}

fn json(args: &[&str]) -> Value {
    let mut all = args.to_vec();
    all.push("--json");
    serde_json::from_str(&ok(&all)).unwrap_or_else(|e| panic!("{args:?} did not print JSON: {e}"))
}

fn fails_with(args: &[&str], needle: &str) {
    let out = run(args);
    assert!(!out.status.success(), "{args:?} should fail");
    let err = String::from_utf8_lossy(&out.stderr);
    assert!(err.contains(needle), "{args:?}: expected {needle:?} in {err}");
}

#[test]
fn items_can_be_repeated_or_comma_separated() {
    let a = json(&["build", "haze", "-i", "extra health", "-i", "headshot booster"]);
    let b = json(&["build", "haze", "--item", "extra health,headshot booster"]);
    assert_eq!(a["items"], b["items"]);
    assert_eq!(a["items"].as_array().unwrap().len(), 2);
}

#[test]
fn upgrades_parse_and_components_are_consumed() {
    let v = json(&["build", "haze", "-i", "headshot booster", "-i", "headhunter", "-u", "0=2", "-u", "3=1"]);
    assert_eq!(v["items"], serde_json::json!(["Headhunter"]));
    let abilities = v["abilities"].as_array().unwrap();
    assert_eq!((abilities[0]["tier"].as_i64(), abilities[3]["tier"].as_i64()), (Some(2), Some(1)));
    fails_with(&["build", "haze", "-u", "0=7"], "tier must be between 0 and 3");
    fails_with(&["build", "haze", "-u", "nope"], "index=tier");
}

#[test]
fn share_codes_load_and_can_be_extended() {
    let base = json(&["build", "haze", "-i", "headshot booster", "--souls", "700"]);
    let code = base["share_code"].as_str().unwrap();
    let again = json(&["build", "--code", code]);
    assert_eq!(again["items"], base["items"]);
    assert_eq!(again["souls"]["extra"], 700);
    let extended = json(&["build", "--code", code, "-i", "headhunter"]);
    assert_eq!(extended["items"], serde_json::json!(["Headhunter"]));
    fails_with(&["build", "--code", "v1-garbage"], "malformed");
    fails_with(&["build"], "Specify a hero");
}

#[test]
fn unknown_names_suggest_alternatives() {
    fails_with(&["hero", "hazz"], "Did you mean: Haze");
    fails_with(&["build", "haze", "-i", "hedshot booster"], "Did you mean");
    fails_with(&["rank", "nonsense"], "Unknown stat");
    fails_with(&["optimize", "haze", "--goal", "win"], "Unknown goal");
}

#[test]
fn json_output_is_available_for_calculators() {
    assert!(json(&["heroes"]).as_array().unwrap().iter().any(|h| h == "Haze"));
    assert!(json(&["bullet", "haze", "--boons", "5"])["final_dps"].as_f64().unwrap() > 0.0);
    assert!(json(&["ttk", "haze", "abrams"])["realistic_ttk"].as_f64().unwrap() > 0.0);
    assert!(
        json(&["optimize", "haze", "--goal", "gun", "--budget", "5000"])["result"]["total_cost"].as_i64().unwrap()
            <= 5000
    );
    assert!(
        json(&["simulate", "haze", "--vs", "abrams", "--duration", "5"])["sides"][0]["dps"].as_f64().unwrap() > 0.0
    );
    let mc = json(&["montecarlo", "haze", "--vs", "abrams", "--trials", "200", "--seed", "3"]);
    assert_eq!(
        mc,
        json(&["montecarlo", "haze", "--vs", "abrams", "--trials", "200", "--seed", "3"]),
        "seeded runs repeat"
    );
    assert_eq!(
        json(&["matchups", "haze"])["matchups"].as_array().unwrap().len(),
        json(&["heroes"]).as_array().unwrap().len()
    );
}

#[test]
fn text_output_and_saved_patch_report() {
    assert!(ok(&["hero", "haze"]).contains("Bullet Damage"));
    let patches = ok(&["patch", "--date", "03-25-2026"]);
    assert!(patches.contains("Parsed") && patches.contains("MANUAL REVIEW"));
    fails_with(&["patch", "--date", "01-01-1999"], "No saved patch");
    assert!(ok(&["completions", "bash"]).contains("deadlock-sim"));
}

#[test]
fn interactive_menu_runs_a_lookup_and_quits_on_eof() {
    let mut child =
        Command::new(env!("CARGO_BIN_EXE_deadlock-sim")).stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().unwrap();
    // Menu 1 = hero lookup, then pick hero by name, then end input.
    child.stdin.take().unwrap().write_all(b"1\nhaze\n").unwrap();
    let out = child.wait_with_output().unwrap();
    let text = String::from_utf8_lossy(&out.stdout);
    assert!(out.status.success());
    assert!(text.contains("Haze - Base Stats") && text.contains("Goodbye"), "{text}");
}

#[test]
fn mcp_mode_speaks_json_rpc_over_stdio() {
    let mut child = Command::new(env!("CARGO_BIN_EXE_deadlock-sim"))
        .arg("mcp")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut stdin = child.stdin.take().unwrap();
    writeln!(stdin, r#"{{"jsonrpc":"2.0","id":1,"method":"initialize","params":{{}}}}"#).unwrap();
    writeln!(stdin, r#"{{"jsonrpc":"2.0","method":"notifications/initialized"}}"#).unwrap();
    writeln!(stdin, "this is not json").unwrap();
    writeln!(stdin, r#"{{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{{"name":"list_heroes"}}}}"#).unwrap();
    drop(stdin);
    let out = child.wait_with_output().unwrap();
    let lines: Vec<Value> =
        String::from_utf8(out.stdout).unwrap().lines().map(|l| serde_json::from_str(l).unwrap()).collect();
    assert_eq!(lines.len(), 3, "the notification gets no reply");
    assert_eq!(lines[0]["id"], 1);
    assert_eq!(lines[1]["error"]["code"], -32700);
    assert_eq!(lines[2]["result"]["isError"], false);
}
