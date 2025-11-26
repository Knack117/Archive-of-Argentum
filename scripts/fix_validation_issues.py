"""Fix OpenAPI validation issues in generated JSON files."""
import json
import sys
from pathlib import Path

def fix_validation_issues(json_file: Path) -> None:
    """Fix validation issues in an OpenAPI JSON file."""
    print(f"Fixing validation issues in {json_file}...")
    
    try:
        with open(json_file, 'r') as f:
            schema = json.load(f)
        
        changes_made = 0
        
        # Fix mass-land-destruction description length
        paths = schema.get("paths", {})
        mld_path = paths.get("/api/v1/cards/mass-land-destruction")
        if mld_path and mld_path.get("get"):
            mld_desc = mld_path["get"].get("description", "")
            if len(mld_desc) > 300:
                shortened_desc = (
                    "Get Mass Land Destruction cards from Scryfall matching official MLD criteria. "
                    "Returns cards that regularly destroy, exile, and bounce other lands, "
                    "keep lands tapped, or change mana production by four or more lands per player."
                )
                mld_path["get"]["description"] = shortened_desc
                print(f"  ✓ Fixed mass-land-destruction description (was {len(mld_desc)} chars, now {len(shortened_desc)} chars)")
                changes_made += 1
        
        # Fix missing schema properties for status, root, and health endpoints
        problematic_endpoints = {"/api/v1/status", "/", "/health"}
        
        for endpoint in problematic_endpoints:
            endpoint_data = paths.get(endpoint)
            if endpoint_data:
                for method, method_data in endpoint_data.items():
                    responses = method_data.get("responses", {})
                    if "200" in responses:
                        content = responses["200"].get("content", {})
                        if "application/json" in content:
                            schema = content["application/json"].get("schema", {})
                            # Replace empty schema with proper schema definition
                            if (schema.get("additionalProperties") is True and 
                                "properties" not in schema):
                                schema.update({
                                    "type": "object",
                                    "title": schema.get("title", f"Response {endpoint.replace('/', '').title()}"),
                                    "properties": {
                                        "message": {
                                            "type": "string",
                                            "description": "Response message"
                                        }
                                    },
                                    "required": ["message"]
                                })
                                print(f"  ✓ Fixed schema for {endpoint} endpoint")
                                changes_made += 1
        
        # Save the updated schema
        if changes_made > 0:
            with open(json_file, 'w') as f:
                json.dump(schema, f, indent=2)
            print(f"  ✅ Saved {json_file} with {changes_made} fixes")
        else:
            print(f"  ℹ️ No changes needed for {json_file}")
            
    except Exception as e:
        print(f"  ❌ Error processing {json_file}: {e}")

def main():
    """Fix validation issues in all generated OpenAPI files."""
    schema_files = [
        'system_cards.json',
        'commanders_combos.json', 
        'themes_deck_validation.json',
        'popular_decks_cedh.json'
    ]
    
    print("🔧 Fixing OpenAPI Validation Issues")
    print("=" * 50)
    
    for schema_file in schema_files:
        schema_path = Path(schema_file)
        if schema_path.exists():
            fix_validation_issues(schema_path)
        else:
            print(f"❌ {schema_file} - FILE NOT FOUND")
    
    print(f"\n✅ Validation fixes completed!")

if __name__ == "__main__":
    main()