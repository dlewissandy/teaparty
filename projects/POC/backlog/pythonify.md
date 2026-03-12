I would like to convert the existing tui code from its current state which a hodge-podge of python and bash scripts to one that uses exclusively python code.   The goal of this is twofold:

* Eliminate race conditions that are causing irreproducible behavior in the ui
* Improve the cross-platform portability
* Improve conceptual clarity

Constraints:
Presently we use the cli "claude -p" to invoke the llm.   This must NOT change.   

Success Criteria
* The tui execution is semantically equivalent to the existing script based implementation, but does not call any of the existing *.sh files.

Process
This is a big lift.   I expect that you will need to go file by file to ensure that nothing gets broken.   Do not break teh run.sh script.   That will be removed in a later session.
