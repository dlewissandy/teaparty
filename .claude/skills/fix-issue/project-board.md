# Project Board Helpers

Use these patterns to update the GitHub project board status for an issue.

## Get Item ID

```bash
ITEM_ID=$(gh api graphql -f query='{
  user(login: "dlewissandy") {
    projectV2(number: 2) {
      items(first: 100) {
        nodes { id content { ... on Issue { number } } }
      }
    }
  }
}' --jq '.data.user.projectV2.items.nodes[] | select(.content.number == ISSUE_NUM) | .id')
```

Replace `ISSUE_NUM` with the actual issue number.

## Set Status

```bash
gh api graphql -f query="mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: \"PVT_kwHOAH4OHc4BR81E\"
    itemId: \"${ITEM_ID}\"
    fieldId: \"PVTSSF_lAHOAH4OHc4BR81Ezg_oGbs\"
    value: { singleSelectOptionId: \"OPTION_ID\" }
  }) { projectV2Item { id } }
}"
```

Status option IDs:
- **In Progress:** `71f64e69`
- **Done:** `42fb9610`
