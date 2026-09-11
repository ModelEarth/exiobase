import pandas as pd

import pymrio


year = 2013

base_exio_path = "H:\Exiobase Unzipped\IOT_"
exio_path = base_exio_path + str(year) + "_pxp"
countries_path = r"C:\Users\garma\Downloads\exio_country_names.csv"



#exio_model.calc_all()

exio_model = pymrio.parse_exiobase3(exio_path)

import pandas as pd


extensions_to_use = ['air_emissions', 'employment', 'energy', 'factor_inputs', 'land', 'material', 'nutrients', 'water']


# Step 1: Pick extension, e.g., employment
#ext_name = "air_emissions"

for ext_name in extensions_to_use:
    ext = getattr(exio_model, ext_name).F.copy()

    # Step 2: Normalize column MultiIndex to flat "region|product"
    ext.columns = [f"{region}|{product}" for region, product in ext.columns]

    # Step 3: Melt to long format
    df_ext = ext.reset_index(names='indicator')
    df_ext = df_ext.melt(id_vars='indicator', var_name='region_product', value_name='value')
    df_ext[['region', 'product']] = df_ext['region_product'].str.split("|", expand=True)
    df_ext.drop(columns='region_product', inplace=True)




    # Step 1: Copy original Z matrix
    Z = exio_model.Z.copy()

    # Step 2: Ensure names are assigned
    Z.index.names = ['from_region', 'from_product']
    Z.columns.names = ['to_region', 'to_product']

    # Step 3: Stack the column MultiIndex into rows
    Z_stacked = Z.stack(level=['to_region', 'to_product'], future_stack=True).reset_index()

    # Step 4: Rename the columns
    Z_stacked.columns = ['from_region', 'from_product', 'to_region', 'to_product', 'flow']

    # Step 5: Optional - filter out 0 flows
    Z_stacked = Z_stacked[Z_stacked['flow'] != 0]
    #Z_stacked = Z_stacked.head(1000)
    ########## .head(1000)
    
    Z_stacked = Z_stacked
    
    # Step 5: Merge Z with extension factors
    
    
    #df = Z_stacked.merge(df_ext.head(1000), left_on=['from_region', 'from_product'], right_on=['region', 'product'], how='left')
    ######### df_ext.head(1000) 
    
    df = Z_stacked.merge(df_ext, left_on=['from_region', 'from_product'], right_on=['region', 'product'], how='left')
    df.drop(columns=['region', 'product'], inplace=True)

    # Step 6: Calculate impact = flow × factor value
    df['impact'] = df['flow'] * df['value']

    # Step 7: Final formatting
    df_final = df[['from_region', 'to_region', 'from_product', 'indicator', 'impact']].copy()
    df_final.columns = ['FromRegion', 'ToRegion', 'Product', 'Indicator', 'Value']
    df_final['Year'] = 2013  # Adjust to match your dataset
    df_final['Unit'] = 'unit from extension metadata'
    df_final['Factor'] = ext_name

    countries = pd.read_csv(countries_path)

    df_final = pd.merge(df_final, countries, how='inner', left_on=['FromRegion'], right_on=['CountryCode'])
    df_final.rename(columns={'Country': 'FromCountry'}, inplace=True)

    df_final = pd.merge(df_final, countries, how='inner', left_on=['ToRegion'], right_on=['CountryCode'])
    df_final.rename(columns={'Country': 'ToCountry'}, inplace=True)

    df_final.drop(columns=['FromRegion', 'ToRegion', 'CountryCode_x', 'CountryCode_y'], inplace=True)

    # insert postgres make columns for postgres
    df_final.columns = [
        'product_category',
        'impact_category',
        'level',
        'year',
        'unit',
        'factor',
        'from_country',
        'to_country'
    ]


    df_final.head()

    insert_postgres('producttradeimpact', df_final.head(100), user, password, host, port, database)

    # end of postgres insertion



# below is the more correct

''' 
import pandas as pd

# Step 1: Pick extension, e.g., air_emissions
ext_name = "air_emissions"
ext = getattr(exio_model, ext_name).F.copy()

# Step 2: Flatten MultiIndex columns into strings: region|product
ext.columns = [f"{region}|{product}" for region, product in ext.columns]

# Step 3: Melt extension into long format
df_ext = ext.reset_index(names='indicator')
df_ext = df_ext.melt(id_vars='indicator', var_name='region_product', value_name='value')
df_ext[['region', 'product']] = df_ext['region_product'].str.split("|", expand=True)
df_ext.drop(columns='region_product', inplace=True)

# Step 4: Prepare Z matrix (inter-industry flows)
Z = exio_model.Z.copy()
Z.index.names = ['from_region', 'from_product']
Z.columns.names = ['to_region', 'to_product']
Z_stacked = Z.stack(level=['to_region', 'to_product'], future_stack=True).reset_index()
Z_stacked.columns = ['from_region', 'from_product', 'to_region', 'to_product', 'flow']
Z_stacked = Z_stacked[Z_stacked['flow'] != 0]

# Step 5: Chunked merge to avoid memory error
chunk_size = 500_000
chunks = []

for i in range(0, len(Z_stacked), chunk_size):
    chunk = Z_stacked.iloc[i:i+chunk_size]
    merged = chunk.merge(df_ext, left_on=['from_region', 'from_product'],
                         right_on=['region', 'product'], how='left')
    merged.drop(columns=['region', 'product'], inplace=True)
    chunks.append(merged)

df = pd.concat(chunks, ignore_index=True)

# Step 6: Calculate impact = flow × value
df['impact'] = df['flow'] * df['value']

# Step 7: Final formatting
df_final = df[['from_region', 'to_region', 'from_product', 'indicator', 'impact']]
df_final.columns = ['FromRegion', 'ToRegion', 'Product', 'Indicator', 'Value']
df_final['Year'] = 2013  # Set to actual year of your data
df_final['Unit'] = 'unit from extension metadata'  # Replace with real unit
df_final['Source'] = ext_name  # Will be "air_emissions"

# Preview
print(df_final.head())
'''
