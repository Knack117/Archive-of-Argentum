"""Verification script to check operation counts in generated OpenAPI schemas."""
import json
from pathlib import Path

def count_operations_in_schema(file_path: Path) -> int:
    """Count the number of operations in an OpenAPI schema."""
    try:
        with open(file_path, 'r') as f:
            schema = json.load(f)
        
        paths = schema.get('paths', {})
        operation_count = sum(len(methods) for methods in paths.values())
        return operation_count
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return 0

def main():
    """Verify all generated OpenAPI schemas."""
    schema_files = [
        'system_cards.json',
        'commanders_combos.json', 
        'themes_deck_validation.json',
        'popular_decks_cedh.json'
    ]
    
    print("🔍 Verifying OpenAPI Schema Operation Counts")
    print("=" * 60)
    
    total_operations = 0
    max_operations = 30
    
    for schema_file in schema_files:
        file_path = Path(schema_file)
        if file_path.exists():
            operation_count = count_operations_in_schema(file_path)
            total_operations += operation_count
            
            # Load schema for additional info
            with open(file_path, 'r') as f:
                schema = json.load(f)
            
            title = schema.get('info', {}).get('title', 'Unknown')
            description = schema.get('info', {}).get('description', 'No description')
            
            status = "✅ PASS" if operation_count <= max_operations else "❌ FAIL"
            
            print(f"\n{status} {schema_file}")
            print(f"   Title: {title}")
            print(f"   Operations: {operation_count}/{max_operations}")
            print(f"   Description: {description}")
            
        else:
            print(f"❌ {schema_file} - FILE NOT FOUND")
    
    print(f"\n{'=' * 60}")
    print(f"📊 Total Operations Across All Schemas: {total_operations}")
    print(f"📊 Maximum Allowed per Action: {max_operations}")
    
    if total_operations > 0:
        estimated_actions_needed = (total_operations + max_operations - 1) // max_operations
        print(f"📊 Estimated Actions Needed: {estimated_actions_needed}")
    
    all_within_limit = all(
        count_operations_in_schema(Path(f)) <= max_operations 
        for f in schema_files if Path(f).exists()
    )
    
    if all_within_limit:
        print(f"\n✅ All schemas comply with the {max_operations} operation limit!")
    else:
        print(f"\n❌ Some schemas exceed the {max_operations} operation limit!")

if __name__ == "__main__":
    main()