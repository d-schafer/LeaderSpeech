#.....................................................................
# Key for fixing leaders names
#




#Making this into a function to fix the names of the leaders in any given dataset

fixNames <- function(dataframe, speaker, year) {
  
  
  #...................................
  # First 200 rows
  
  # Standardize Leader Names for Albania
  dataframe$speaker[dataframe$country == "Albania" & dataframe$speaker %in% c("Edi Rama", "Rama")] <- "Edi Rama"
  dataframe$speaker[dataframe$country == "Albania" & dataframe$speaker == "Meidani"] <- "Rexhep Meidani"
  #Berisha
  dataframe$speaker[dataframe$country == "Albania" & dataframe$speaker == "Berisha"] <- "Sali Berisha"
  
  # Standardize Leader Names for Argentina
  dataframe$speaker[dataframe$country == "Argentina" & dataframe$speaker %in% c("Cristina Fernandez", "Fernandez de Kirchner")] <- "Cristina Fernandez de Kirchner"
  dataframe$speaker[dataframe$country == "Argentina" & dataframe$speaker %in% c("Mauricio Macri", "Macri")] <- "Mauricio Macri"
  #Menem
  dataframe$speaker[dataframe$country == "Argentina" & dataframe$speaker == "Menem"] <- "Carlos Menem"
  #de la Rua
  dataframe$speaker[dataframe$country == "Argentina" & dataframe$speaker == "De la Rua"] <- "Fernando de la Rua"
  dataframe$speaker[dataframe$country == "Argentina" & dataframe$speaker == "de la Rua"] <- "Fernando de la Rua"
  
  # Standardize Leader Names for Armenia
  dataframe$speaker[dataframe$country == "Armenia" & dataframe$speaker %in% c("Serzh Azati Sargsyan", "Sargsyan")] <- "Serzh Sargsyan"
  dataframe$speaker[dataframe$country == "Armenia" & dataframe$speaker %in% c("Kocharian", "Robert Kocharian")] <- "Robert Kocharyan"
  dataframe$speaker[dataframe$country == "Armenia" & dataframe$speaker == "Karapetyan"] <- "Karen Karapetyan"
  dataframe$speaker[dataframe$country == "Armenia" & dataframe$speaker == "Pashinyan"] <- "Nikol Pashinyan"
  dataframe$speaker[dataframe$country == "Armenia" & dataframe$speaker %in% c("Sarkissian", "Sarkisian", "Sarkissyan")] <- "Armen Sarkissian"
  dataframe$speaker[dataframe$country == "Armenia" & dataframe$speaker %in% c("Kocharyan") ] <- "Robert Kocharyan"

  
  # Standardize Leader Names for Australia
  dataframe$speaker[dataframe$country == "Australia" & dataframe$speaker %in% c("Howard", "John Howard")] <- "John Howard"
  dataframe$speaker[dataframe$country == "Australia" & dataframe$speaker %in% c("Gillard", "Julia Gillard")] <- "Julia Gillard"
  dataframe$speaker[dataframe$country == "Australia" & dataframe$speaker %in% c("Rudd", "Kevin Rudd")] <- "Kevin Rudd"
  dataframe$speaker[dataframe$country == "Australia" & dataframe$speaker %in% c("Abbott", "Tony Abbott")] <- "Tony Abbott"
  dataframe$speaker[dataframe$country == "Australia" & dataframe$speaker %in% c("Turnbull", "Malcolm Turnbull")] <- "Malcolm Turnbull"
  dataframe$speaker[dataframe$country == "Australia" & dataframe$speaker %in% c("Morrison", "Scott Morrison")] <- "Scott Morrison"
  dataframe$speaker[dataframe$country == "Australia" & dataframe$speaker %in% c("Albanese", "Anthony Albanese")] <- "Anthony Albanese"
  

  # Standardize Leader Names for Austria
  dataframe$speaker[dataframe$country == "Austria" & dataframe$speaker %in% c("Wolfgang Schussel", "Wolfgang Schüssel", "Schussel")] <- "Wolfgang Schüssel"
  dataframe$speaker[dataframe$country == "Austria" & dataframe$speaker == "Gusenbauer"] <- "Alfred Gusenbauer"
  dataframe$speaker[dataframe$country == "Austria" & dataframe$speaker == "Faymann"] <- "Werner Faymann"
  dataframe$speaker[dataframe$country == "Austria" & dataframe$speaker == "Kurz"] <- "Sebastian Kurz"
  dataframe$speaker[dataframe$country == "Austria" & dataframe$speaker == "Kern"] <- "Christian Kern"
  dataframe$speaker[dataframe$country == "Austria" & dataframe$speaker == "Nehammer"] <- "Karl Nehammer"
  dataframe$speaker[dataframe$country == "Austria" & dataframe$speaker == "Schallenberg"] <- "Alexander Schallenberg"

  # Standardize Leader Names for Azerbaijan
  dataframe$speaker[dataframe$country == "Azerbaijan" & dataframe$speaker %in% c("Ilhma Aliyev", "Ilham Aliyev")] <- "Ilham Aliyev"
  
  # Standardize Leader Names for Belarus
  dataframe$speaker[dataframe$country == "Belarus" & dataframe$speaker %in% c("Alexander Lukashenko", "Lukashenko")] <- "Alexander Lukashenko"
  dataframe$speaker[dataframe$country == "Belarus" & dataframe$speaker == "Kobyakov"] <- "Andrei Kobyakov"
  dataframe$speaker[dataframe$country == "Belarus" & dataframe$speaker %in% c("Rumas", "Sergei Rumas")] <- "Sergey Rumas"
  dataframe$speaker[dataframe$country == "Belarus" & dataframe$speaker == "Golovchenko"] <- "Roman Golovchenko"
  
  # Standardize Leader Names for Belgium
  dataframe$speaker[dataframe$country == "Belgium" & dataframe$speaker == "Dehaene"] <- "Jean-Luc Dehaene"
  dataframe$speaker[dataframe$country == "Belgium" & dataframe$speaker == "Verhofstadt"] <- "Guy Verhofstadt"
  dataframe$speaker[dataframe$country == "Belgium" & dataframe$speaker == "van Rompuy"] <- "Herman Van Rompuy"
  dataframe$speaker[dataframe$country == "Belgium" & dataframe$speaker == "Leterme"] <- "Yves Leterme"
  
  
  # Print to verify some of the changes
  # print(dataframe %>% filter(country == "Albania"), n = 200)
  # print(dataframe %>% filter(country == "Australia"), n = 200)
  # print(dataframe %>% filter(country == "Belarus"), n = 200)
  
  
  
  
  # Standardize Leader Names for Bangladesh
  dataframe$speaker[dataframe$country == "Bangladesh" & dataframe$speaker == "Fakhruddin"] <- "Fakhruddin Ahmed"
  
  # Standardize Leader Names for Barbados
  dataframe$speaker[dataframe$country == "Barbados" & dataframe$speaker == "Stuart"] <- "Freundel Stuart"
  
  # Standardize Leader Names for Belarus (continuation)
  dataframe$speaker[dataframe$country == "Belarus" & dataframe$speaker == "Kobyakov" & dataframe$year >= 2014 & dataframe$year <= 2018] <- "Andrei Kobyakov"
  dataframe$speaker[dataframe$country == "Belarus" & dataframe$speaker == "Rumas" & dataframe$year == 2018] <- "Sergey Rumas"
  
  # Additional check and recoding for Belgium
  dataframe$speaker[dataframe$country == "Belgium" & dataframe$speaker == "Leterme" & dataframe$year == 2011] <- "Yves Leterme"
  dataframe$speaker[dataframe$country == "Belgium" & dataframe$speaker == "van Rompuy"] <- "Herman Van Rompuy"
  
  # Example of recoding trivial misspecified speakers
  dataframe$speaker[dataframe$country == "Venezuela" & dataframe$year == 1999 & dataframe$speaker == "Nicolas Maduro"] <- "Hugo Chavez"
  dataframe$speaker[dataframe$country == "Albania" & dataframe$year == 2005 & dataframe$speaker == "Berisha"] <- "Sali Berisha"
  
  
  # Print to verify all changes were effective
  # print(dataframe %>% filter(country == "Bangladesh"), n = 20)
  # print(dataframe %>% filter(country == "Barbados"), n = 20)
  # print(dataframe %>% filter(country == "Belarus"), n = 20)
  # print(dataframe %>% filter(country == "Belgium"), n = 20)
  # print(dataframe %>% filter(country == "Venezuela"), n = 20)
  
  
  
  
  #................................................
  # Next 800 rows
  
  # Standardize Leader Names for Belgium (continuation)
  dataframe$speaker[dataframe$country == "Belgium" & dataframe$speaker == "Sophie Wilmes"] <- "Sophie Wilmès"
    
  # Standardize Leader Names for Bhutan (continuation)
  dataframe$speaker[dataframe$country == "Bhutan" & dataframe$speaker == "Lotay Tshering"] <- "Lotay Tshering"
  
  # Standardize Leader Names for Bolivia
  dataframe$speaker[dataframe$country == "Bolivia" & dataframe$speaker == "Gonzalo Sanchez de Lozada"] <- "Gonzalo Sánchez de Lozada"
  
  # Standardize Leader Names for Botswana
  dataframe$speaker[dataframe$country == "Botswana" & dataframe$speaker == "Mogae"] <- "Festus Mogae"
  dataframe$speaker[dataframe$country == "Botswana" & dataframe$speaker == "Ian Khama"] <- "Ian Khama"
  
  
  # Standardize Leader Names for Bulgaria
  dataframe$speaker[dataframe$country == "Bulgaria" & dataframe$speaker %in% c("Saksgoburggotski", "Simeon Borisov Sakskoburggotski")] <- "Simeon Saxe-Coburg-Gotha"
  dataframe$speaker[dataframe$country == "Bulgaria" & dataframe$speaker %in% c("Boyko Borisov", "Boiko Borisov")] <- "Boyko Borissov"
  dataframe$speaker[dataframe$country == "Bulgaria" & dataframe$speaker == "Donev"] <- "Galab Donev"

  # Standardize Leader Names for Brazil
  dataframe$speaker[dataframe$country == "Brazil" & dataframe$speaker == "Cardoso"] <- "Fernando Henrique Cardoso"
  dataframe$speaker[dataframe$country == "Brazil" & dataframe$speaker == "Fernando Henrique Cardoso"] <- "Fernando Henrique Cardoso"
  dataframe$speaker[dataframe$country == "Brazil" & dataframe$speaker %in% c("Luiz Inacio Lula da Silva", "Luiz Inácio Lula da Silva",
                                                                             "Lula da Silva")] <- "Luiz Inácio Lula da Silva"
  #Lete's simplify Lula's name a little
  dataframe$speaker[dataframe$country == "Brazil" & dataframe$speaker %in% c("Luiz Inácio Lula da Silva")] <- "Lula da Silva"
  
  #
  dataframe$speaker[dataframe$country == "Brazil" & dataframe$speaker %in% c("Dilma Rousseff", "Roussef", "Rousseff")] <- "Dilma Rousseff"
  dataframe$speaker[dataframe$country == "Brazil" & dataframe$speaker == "Temer"] <- "Michel Temer"
  dataframe$speaker[dataframe$country == "Brazil" & dataframe$speaker %in% c("Jair Bolsonaro", "Bolsonaro")] <- "Jair Bolsonaro"
  #and just Bolsonaro

  # Standardize Leader Names for Bulgaria
  dataframe$speaker[dataframe$country == "Bulgaria" & dataframe$speaker == "Kostov"] <- "Ivan Kostov"
  dataframe$speaker[dataframe$country == "Bulgaria" & dataframe$speaker %in% c("Saksgoburggotski", "Simeon Borisov Sakskoburggotski")] <- "Simeon Saxe-Coburg-Gotha"
  dataframe$speaker[dataframe$country == "Bulgaria" & dataframe$speaker %in% c("Sergei Stanishev", "Stanishev")] <- "Sergei Stanishev"
  dataframe$speaker[dataframe$country == "Bulgaria" & dataframe$speaker == "Boyko Borisov"] <- "Boyko Borissov"
  
  # Standardize Leader Names for Burundi
  dataframe$speaker[dataframe$country == "Burundi" & dataframe$speaker == "Nkurunziza"] <- "Pierre Nkurunziza"
  
  # Standardize Leader Names for Cameroon
  dataframe$speaker[dataframe$country == "Cameroon" & dataframe$speaker %in% c("Biya", "Paul Biya")] <- "Paul Biya"
  dataframe$speaker[dataframe$country == "Cameroon" & dataframe$speaker == "Ngute"] <- "Joseph Ngute"
  
  # Standardize Leader Names for Canada
  dataframe$speaker[dataframe$country == "Canada" & dataframe$speaker %in% c("Jean Chretien", "Jean Chrétien", "Chretien")] <- "Jean Chrétien"
  dataframe$speaker[dataframe$country == "Canada" & dataframe$speaker %in% c("Paul Martin", "Martin")] <- "Paul Martin"
  dataframe$speaker[dataframe$country == "Canada" & dataframe$speaker %in% c("Stephen Harper", "Harper")] <- "Stephen Harper"
  dataframe$speaker[dataframe$country == "Canada" & dataframe$speaker %in% c("Justin Trudeau", "Trudeau")] <- "Justin Trudeau"

  # Standardize Leader Names for Chile
  dataframe$speaker[dataframe$country == "Chile" & dataframe$speaker %in% c("Ricardo Lagos", "Ricardo Lagos Escobar")] <- "Ricardo Lagos"
  dataframe$speaker[dataframe$country == "Chile" & dataframe$speaker %in% c("Michelle Bachelet", "Bachelet")] <- "Michelle Bachelet"
  dataframe$speaker[dataframe$country == "Chile" & dataframe$speaker %in% c("Sebastian Pinera", "Sebastián Piñera", "Pinera")] <- "Sebastián Piñera"
  
  # Standardize Leader Names for Colombia
  dataframe$speaker[dataframe$country == "Colombia" & dataframe$speaker == "Andres Pastrana"] <- "Andrés Pastrana"
  dataframe$speaker[dataframe$country == "Colombia" & dataframe$speaker %in% c("Alvaro Uribe", "Álvaro Uribe","Uribe Velez", "Alvaro Uribe Velez")] <- "Álvaro Uribe Vélez"
  dataframe$speaker[dataframe$country == "Colombia" & dataframe$speaker == "Juan Manuel Santos"] <- "Juan Manuel Santos"
  dataframe$speaker[dataframe$country == "Colombia" & dataframe$speaker == "Santos Calderon"] <- "Juan Manuel Santos"
  


  
  # Standardize Leader Names for Costa Rica
  dataframe$speaker[dataframe$country == "Costa Rica" & dataframe$speaker %in% c("Miguel Angel Rodriguez", "Rodriguez Echeverria")] <- "Miguel Ángel Rodríguez"
  dataframe$speaker[dataframe$country == "Costa Rica" & dataframe$speaker == "Abel Pacheco"] <- "Abel Pacheco"
  dataframe$speaker[dataframe$country == "Costa Rica" & dataframe$speaker %in% c("Oscar Arias", "Arias")] <- "Óscar Arias"
  dataframe$speaker[dataframe$country == "Costa Rica" & dataframe$speaker %in% c("Miranda","Laura Chinchilla")] <- "Laura Chinchilla Miranda"
  dataframe$speaker[dataframe$country == "Costa Rica" & dataframe$speaker == "Luis Guillermo Solis"] <- "Luis Guillermo Solís"
  
  # Standardize Leader Names for Croatia
  dataframe$speaker[dataframe$country == "Croatia" & dataframe$speaker %in% c("Franjo Tudman", "Tudman", "Tudjman")] <- "Franjo Tuđman"
  dataframe$speaker[dataframe$country == "Croatia" & dataframe$speaker == "Ivica Racan"] <- "Ivica Račan"
  dataframe$speaker[dataframe$country == "Croatia" & dataframe$speaker == "Racan"] <- "Ivica Račan"
  dataframe$speaker[dataframe$country == "Croatia" & dataframe$speaker == "Milanovic"] <- "Zoran Milanović"
  dataframe$speaker[dataframe$country == "Croatia" & dataframe$speaker == "Plenkovic"] <- "Andrej Plenković"
  dataframe$speaker[dataframe$country == "Croatia" & dataframe$speaker == "Andrej Plenkovic"] <- "Andrej Plenković"
  dataframe$speaker[dataframe$country == "Croatia" & dataframe$speaker == "Pavletic"] <- "Vlatko Pavletic"

  # Standardize Leader Names for Cuba
  dataframe$speaker[dataframe$country == "Cuba" & dataframe$speaker == "Castro"] <- "Fidel Castro"
  
  # Standardize Leader Names for Cyprus
  dataframe$speaker[dataframe$country == "Cyprus" & dataframe$speaker == "Nikos Anastasiadis"] <- "Nikos Anastasiades"
  
  
  #Czechia
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Vladimír Spidla"] <- "Vladimir Spidla"
  # Standardize Leader Names for Czechia
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Klaus"] <- "Vaclav Klaus"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Havel"] <- "Vaclav Havel"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Paroubek"] <- "Jiri Paroubek"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker %in% c("Milos Zeman", "Zeman")] <- "Milos Zeman"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Spidla"] <- "Vladimír Spidla"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Topolanek"] <- "Mirek Topolanek"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Necas"] <- "Petr Necas"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Sobotka"] <- "Bohuslav Sobotka"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker %in% c("Fiala", "Pietr Fiala")] <- "Petr Fiala"
  #getting rid of accents from Vladimír Špidla, Petr Nečas, Václav Havel, Václav Klaus, Mirek Topolánek, Miloš Zeman, Jiří Paroubek
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Vladimír Špidla"] <- "Vladimir Spidla"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Petr Nečas"] <- "Petr Necas"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Václav Havel"] <- "Vaclav Havel"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Václav Klaus"] <- "Vaclav Klaus"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Mirek Topolánek"] <- "Mirek Topolanek"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker %in% c("Miloš Zeman", "Milo Zeman")] <- "Milos Zeman"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Jiří Paroubek"] <- "Jiri Paroubek"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Jiří Rusnok"] <- "Jiri Rusnok"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Tosovsky"] <- "Josef Tosovsky"
  dataframe$speaker[dataframe$country == "Czechia" & dataframe$speaker == "Fischer"] <- "Jan Fischer"

  
  
  # Standardize Leader Names for Denmark
  dataframe$speaker[dataframe$country == "Denmark" & dataframe$speaker %in% c("Nyrup Rasmussen", "Poul Nyrup Rasmussen")] <- "Poul Nyrup Rasmussen"
  dataframe$speaker[dataframe$country == "Denmark" & dataframe$speaker %in% c("Lars Løkke Rasmussen", "Lokke Rasmussen", "Lars Lokke Rasmussen")] <- "Lars Løkke Rasmussen"
  dataframe$speaker[dataframe$country == "Denmark" & dataframe$speaker == "Thorning-Schmidt"] <- "Helle Thorning-Schmidt"
  
  # Standardize Leader Names for Dominican Republic
  dataframe$speaker[dataframe$country == "Dominican Republic" & dataframe$speaker %in% c("Leonel Fernandez", "Fernandez", "Fernandez Reyna")] <- "Leonel Fernández"
  
  # Standardize Leader Names for Ecuadoria
  dataframe$speaker[dataframe$country == "Ecuador" & dataframe$speaker == "Lucio Gutierrez"] <- "Lucio Gutiérrez"
  dataframe$speaker[dataframe$country == "Ecuador" & dataframe$speaker == "Rafael Correa"] <- "Rafael Correa Delgado"
  dataframe$speaker[dataframe$country == "Ecuador" & dataframe$speaker == "Lenin Moreno"] <- "Lenín Moreno"
  
  # Standardize Leader Names for El Salvador
  dataframe$speaker[dataframe$country == "El Salvador" & dataframe$speaker == "Salvador Sanchez Ceren"] <- "Salvador Sánchez Cerén"
  # El Salvador
  dataframe$speaker[dataframe$country == "El Salvador" & dataframe$speaker == "Flores"] <- "Francisco Flores"
  dataframe$speaker[dataframe$country == "El Salvador" & dataframe$speaker == "Saca Gonzšlez"] <- "Antonio Saca"
  dataframe$speaker[dataframe$country == "El Salvador" & dataframe$speaker == "Funes"] <- "Mauricio Funes"
  
  
  # Standardize Leader Names for Estonia
  dataframe$speaker[dataframe$country == "Estonia" & dataframe$speaker == "Vahi"] <- "Tiit Vähi"
  dataframe$speaker[dataframe$country == "Estonia" & dataframe$speaker == "Siimann"] <- "Mart Siimann"
  dataframe$speaker[dataframe$country == "Estonia" & dataframe$speaker == "Laar"] <- "Mart Laar"
  dataframe$speaker[dataframe$country == "Estonia" & dataframe$speaker == "Roivas"] <- "Taavi Rõivas"
  dataframe$speaker[dataframe$country == "Estonia" & dataframe$speaker == "Ratas"] <- "Jüri Ratas"
  #and Ansip
  dataframe$speaker[dataframe$country == "Estonia" & dataframe$speaker == "Ansip"] <- "Andrus Ansip"
  #and Kallas
  dataframe$speaker[dataframe$country == "Estonia" & dataframe$speaker == "Kallas"] <- "Kaja Kallas"
  dataframe$speaker[dataframe$country == "Estonia" & dataframe$speaker == "Parts"] <- "Juhan Parts"

  # Standardize Leader Names for Eswatini
  dataframe$speaker[dataframe$country == "Eswatini" & dataframe$speaker == "Mswati"] <- "King Mswati III"
  dataframe$speaker[dataframe$country == "Eswatini" & dataframe$speaker == "Ambrose Mandvulo Dlamini"] <- "Ambrose Dlamini"
  
  # Standardize Leader Names for Ethiopia
  dataframe$speaker[dataframe$country == "Ethiopia" & dataframe$speaker == "Desalegn"] <- "Hailemariam Desalegn"
  
  # Standardize Leader Names for Fiji
  dataframe$speaker[dataframe$country == "Fiji" & dataframe$speaker == "Bainimarama"] <- "Frank Bainimarama"
  dataframe$speaker[dataframe$country == "Fiji" & dataframe$speaker == "Rabuka"] <- "Sitiveni Rabuka"
  
  # Standardize Leader Names for Finland
  dataframe$speaker[dataframe$country == "Finland" & dataframe$speaker == "Lipponen"] <- "Paavo Lipponen"
  dataframe$speaker[dataframe$country == "Finland" & dataframe$speaker == "Vanhanen"] <- "Matti Vanhanen"
  dataframe$speaker[dataframe$country == "Finland" & dataframe$speaker == "Jurki Katainen"] <- "Jyrki Katainen"
  dataframe$speaker[dataframe$country == "Finland" & dataframe$speaker == "Katainen"] <- "Jyrki Katainen"
  dataframe$speaker[dataframe$country == "Finland" & dataframe$speaker == "Juha Sipilä"] <- "Juha Sipilä"
  dataframe$speaker[dataframe$country == "Finland" & dataframe$speaker == "Sipila"] <- "Juha Sipilä"
  dataframe$speaker[dataframe$country == "Finland" & dataframe$speaker == "Stubb"] <- "Alexander Stubb"

  # Standardize Leader Names for France
  dataframe$speaker[dataframe$country == "France" & dataframe$speaker %in% c("Francois Hollande", "Hollande")] <- "François Hollande"
  dataframe$speaker[dataframe$country == "France" & dataframe$speaker == "Jacques Chirac"] <- "Jacques Chirac"
  dataframe$speaker[dataframe$country == "France" & dataframe$speaker == "Chirac"] <- "Jacques Chirac"
  dataframe$speaker[dataframe$country == "France" & dataframe$speaker == "Sarkozy"] <- "Nicolas Sarkozy"
  dataframe$speaker[dataframe$country == "France" & dataframe$speaker == "Macron"] <- "Emmanuel Macron"
  dataframe$speaker[dataframe$country == "France" & dataframe$speaker == "Valls"] <- "Manuel Valls"
  dataframe$speaker[dataframe$country == "France" & dataframe$speaker == "Borne"] <- "Élisabeth Borne"
  dataframe$speaker[dataframe$country == "France" & dataframe$speaker == "Philippe"] <- "Edouard Philippe"

  # Standardize Leader Names for Georgia
  dataframe$speaker[dataframe$country == "Georgia" & dataframe$speaker %in% c("Mikheil Saakashvili", "Saakashvili")] <- "Mikheil Saakashvili"
  dataframe$speaker[dataframe$country == "Georgia" & dataframe$speaker %in% c("Giorgi Margvelashvili", "Margvelashvili")] <- "Giorgi Margvelashvili"
  dataframe$speaker[dataframe$country == "Georgia" & dataframe$speaker == "Burdzhanadze"] <- "Nino Burdzhanadze"
  dataframe$speaker[dataframe$country == "Georgia" & dataframe$speaker == "Gakharia"] <- "Giorgi Gakharia"
  
  # Standardize Leader Names for Germany
  dataframe$speaker[dataframe$country == "Germany" & dataframe$speaker %in% c("Gerhard Schroeder", "Schroder")] <- "Gerhard Schröder"
  dataframe$speaker[dataframe$country == "Germany" & dataframe$speaker %in% c("Angela Merkel", "Andrea Merkel", "Merkel")] <- "Angela Merkel"
  dataframe$speaker[dataframe$country == "Germany" & dataframe$speaker == "Scholz"] <- "Olaf Scholz"
  
  # Standardize Leader Names for Ghana
  dataframe$speaker[dataframe$country == "Ghana" & dataframe$speaker == "Atta Mills"] <- "John Atta Mills"
  dataframe$speaker[dataframe$country == "Ghana" & dataframe$speaker == "Mahama"] <- "John Dramani Mahama"
  dataframe$speaker[dataframe$country == "Ghana" & dataframe$speaker == "Akufo-Addo"] <- "Nana Akufo-Addo"
  
  # Standardize Leader Names for Greece
  dataframe$speaker[dataframe$country == "Greece" & dataframe$speaker == "Simitis"] <- "Kostas Simitis"
  dataframe$speaker[dataframe$country == "Greece" & dataframe$speaker %in% c("Alexis Tspiras", "Tsipras")] <- "Alexis Tsipras"
  dataframe$speaker[dataframe$country == "Greece" & dataframe$speaker == "Samaras"] <- "Antonis Samaras"
  dataframe$speaker[dataframe$country == "Greece" & dataframe$speaker == "Mitsotakis"] <- "Kyriakos Mitsotakis"

  # Standardize Leader Names for Guatemala
  dataframe$speaker[dataframe$country == "Guatemala" & dataframe$speaker %in% c("Otto Perez Molina", "Molina")] <- "Otto Pérez Molina"
  dataframe$speaker[dataframe$country == "Guatemala" & dataframe$speaker == "Morales"] <- "Jimmy Morales"
  #Berger Perdomo to Oscar Berger
  dataframe$speaker[dataframe$country == "Guatemala" & dataframe$speaker == "Berger Perdomo"] <- "Oscar Berger"
  #and Colom to Alvaro Colom Caballero
  dataframe$speaker[dataframe$country == "Guatemala" & dataframe$speaker == "Colom"] <- "Alvaro Colom Caballero"
  
  
  # Standardize Leader Names for Guyana
  dataframe$speaker[dataframe$country == "Guyana" & dataframe$speaker == "David Granger"] <- "David A. Granger"
  
  # Standardize Leader Names for Honduras
  dataframe$speaker[dataframe$country == "Honduras" & dataframe$speaker %in% c("Carlos Flores","Flores Facusse")] <- "Carlos Roberto Flores"
  dataframe$speaker[dataframe$country == "Honduras" & dataframe$speaker == "Lobo"] <- "Porfirio Lobo Sosa"
  
  # Standardize Leader Names for Hungary
  dataframe$speaker[dataframe$country == "Hungary" & dataframe$speaker %in% c("Viktor Orban", "Orban", "Viktor Orbán")] <- "Viktor Orbán"
  dataframe$speaker[dataframe$country == "Hungary" & dataframe$speaker == "Ferenc Gyurcsany"] <- "Ferenc Gyurcsány"
  dataframe$speaker[dataframe$country == "Hungary" & dataframe$speaker == "Horn"] <- "Gyula Horn"
  
  # Standardize Leader Names for Iceland
  dataframe$speaker[dataframe$country == "Iceland" & dataframe$speaker == "Sigurdardottir"] <- "Jóhanna Sigurðardóttir"
  dataframe$speaker[dataframe$country == "Iceland" & dataframe$speaker == "Oddsson"] <- "Davíð Oddsson"
  
  # Standardize Leader Names for India
  dataframe$speaker[dataframe$country == "India" & dataframe$speaker %in% c("Atal Bihari Vajpayee", "Vajpayee")] <- "Atal Bihari Vajpayee"
  dataframe$speaker[dataframe$country == "India" & dataframe$speaker == "Manmohan Singh"] <- "Manmohan Singh"
  dataframe$speaker[dataframe$country == "India" & dataframe$speaker == "Narendra Modi"] <- "Narendra Modi"
  dataframe$speaker[dataframe$country == "India" & dataframe$speaker == "A. P. J. Abdul Kalam"] <- "A.P.J. Abdul Kalam"
  dataframe$speaker[dataframe$country == "India" & dataframe$speaker %in% c("K. R. Narayanan", "Kocheril Raman Narayanan")] <- "K.R. Narayanan"
  dataframe$speaker[dataframe$country == "India" & dataframe$speaker == "Gowda"] <- "H. D. Deve Gowda"
  dataframe$speaker[dataframe$country == "India" & dataframe$speaker == "Rao"] <- "P. V. Narasimha Rao"
  dataframe$speaker[dataframe$country == "India" & dataframe$speaker == "Gujral"] <- "Inder Kumar Gujral"

  # Standardize Leader Names for Indonesia
  dataframe$speaker[dataframe$country == "Indonesia" & dataframe$speaker == "Megawati Sukarnoputri"] <- "Megawati Sukarnoputri"
  dataframe$speaker[dataframe$country == "Indonesia" & dataframe$speaker %in% c("Susilo Bambang Yudhoyono", "Bambang Yudhoyono")] <- "Susilo Bambang Yudhoyono"
  dataframe$speaker[dataframe$country == "Indonesia" & dataframe$speaker == "Joko Widodo"] <- "Joko Widodo"
  
  # Standardize Leader Names for Iran
  dataframe$speaker[dataframe$country == "Iran" & dataframe$speaker == "Khatami"] <- "Mohammad Khatami"
  dataframe$speaker[dataframe$country == "Iran" & dataframe$speaker == "Ahmadinejad"] <- "Mahmoud Ahmadinejad"
  dataframe$speaker[dataframe$country == "Iran" & dataframe$speaker == "Rouhani"] <- "Hassan Rouhani"
  dataframe$speaker[dataframe$country == "Iran" & dataframe$speaker %in% c("Ayatollah Khamenei", "Seyyed Ali Khamenei")] <- "Ali Khamenei"
  
  # Standardize Leader Names for Ireland
  dataframe$speaker[dataframe$country == "Ireland" & dataframe$speaker == "E. Kenny"] <- "Enda Kenny"
  dataframe$speaker[dataframe$country == "Ireland" & dataframe$speaker == "Varadkar"] <- "Leo Varadkar"
  dataframe$speaker[dataframe$country == "Ireland" & dataframe$speaker == "Martin"] <- "Micheál Martin"
  dataframe$speaker[dataframe$country == "Ireland" & dataframe$speaker == "Ahern"] <- "Bertie Ahern"
  dataframe$speaker[dataframe$country == "Ireland" & dataframe$speaker %in% c("Cowen","B. Cowen")] <- "Brian Cowen"
  
  # Standardize Leader Names for Israel
  dataframe$speaker[dataframe$country == "Israel" & dataframe$speaker == "Sharon"] <- "Ariel Sharon"
  dataframe$speaker[dataframe$country == "Israel" & dataframe$speaker == "Olmert"] <- "Ehud Olmert"
  dataframe$speaker[dataframe$country == "Israel" & dataframe$speaker == "Netanyahu"] <- "Benjamin Netanyahu"
  dataframe$speaker[dataframe$country == "Israel" & dataframe$speaker == "Bennet"] <- "Naftali Bennett"
  

  # Standardize Leader Names for Jamaica
  dataframe$speaker[dataframe$country == "Jamaica" & dataframe$speaker == "Golding"] <- "Bruce Golding"
  dataframe$speaker[dataframe$country == "Jamaica" & dataframe$speaker == "Holness"] <- "Andrew Holness"
  dataframe$speaker[dataframe$country == "Jamaica" & dataframe$speaker == "Simpson Miller"] <- "Portia Simpson-Miller"
  
  
  # Standardize Leader Names for Italy
  dataframe$speaker[dataframe$country == "Italy" & dataframe$speaker == "Berlusconi"] <- "Silvio Berlusconi"
  dataframe$speaker[dataframe$country == "Italy" & dataframe$speaker == "Prodi"] <- "Romano Prodi"
  dataframe$speaker[dataframe$country == "Italy" & dataframe$speaker == "Renzi"] <- "Matteo Renzi"
  dataframe$speaker[dataframe$country == "Italy" & dataframe$speaker == "Conte"] <- "Giuseppe Conte"
  dataframe$speaker[dataframe$country == "Italy" & dataframe$speaker == "Meloni"] <- "Giorgia Meloni"
  dataframe$speaker[dataframe$country == "Italy" & dataframe$speaker == "Georgia Meloni"] <- "Giorgia Meloni"
  dataframe$speaker[dataframe$country == "Italy" & dataframe$speaker == "Draghi"] <- "Mario Draghi"
  


  # Standardize Leader Names for Japan
  dataframe$speaker[dataframe$country == "Japan" & dataframe$speaker == "Hashimoto"] <- "Ryutaro Hashimoto"
  dataframe$speaker[dataframe$country == "Japan" & dataframe$speaker == "Obuchi"] <- "Keizo Obuchi"
  dataframe$speaker[dataframe$country == "Japan" & dataframe$speaker %in% c("Mori", "Yoshiro Mori")] <- "Yoshirō Mori"
  dataframe$speaker[dataframe$country == "Japan" & dataframe$speaker == "Koizumi"] <- "Junichiro Koizumi"
  dataframe$speaker[dataframe$country == "Japan" & dataframe$speaker == "Shinzo Abe"] <- "Shinzo Abe"
  dataframe$speaker[dataframe$country == "Japan" & dataframe$speaker == "Taro Aso"] <- "Taro Aso"
  dataframe$speaker[dataframe$country == "Japan" & dataframe$speaker %in% c("Hatoyama", "Hatoyama Yukio")] <- "Yukio Hatoyama"
  dataframe$speaker[dataframe$country == "Japan" & dataframe$speaker == "Naoto Kan"] <- "Naoto Kan"
  dataframe$speaker[dataframe$country == "Japan" & dataframe$speaker == "Noda"] <- "Yoshihiko Noda"
  dataframe$speaker[dataframe$country == "Japan" & dataframe$speaker == "Akihito"] <- "Emperor Akihito"
  
  # Standardize Leader Names for Jordan
  dataframe$speaker[dataframe$country == "Jordan" & dataframe$speaker == "Abdullah Ibn Hussein El-Hashimi"] <- "Abdullah II"
  dataframe$speaker[dataframe$country == "Jordan" & dataframe$speaker %in% c("Abdullah")] <- "Abdullah II" #, "Hani Mulki"
  dataframe$speaker[dataframe$country == "Jordan" & dataframe$speaker == "Dahabi"] <- "Nader al-Dahabi"
  dataframe$speaker[dataframe$country == "Jordan" & dataframe$speaker == "Ensour"] <- "Abdullah Ensour"
  dataframe$speaker[dataframe$country == "Jordan" & dataframe$speaker == "Mulki"] <- "Hani al-Mulki"

  # Standardize Leader Names for Kazakhstan
  dataframe$speaker[dataframe$country == "Kazakhstan" & dataframe$speaker %in% c("Nazarbayev", "Nursultan Nazarbayev I", "Nazarbaev")] <- "Nursultan Nazarbayev"
  dataframe$speaker[dataframe$country == "Kazakhstan" & dataframe$speaker == "Tokayev"] <- "Kassym-Jomart Tokayev"
  dataframe$speaker[dataframe$country == "Kyrgyzstan" & dataframe$speaker == "Atambayev"] <- "Almazbek S. Atambayev"
  # # Print to verify all changes were effective
  
  

  # # Print to verify all changes were effective
  # print(dataframe %>% filter(country == "Denmark"), n = 20)
  # print(dataframe %>% filter(country == "Belgium"), n = 20)
  # print(dataframe %>% filter(country == "Bhutan"), n = 20)
  # print(dataframe %>% filter(country == "Bolivia"), n = 20)
  # print(dataframe %>% filter(country == "Botswana"), n = 20)
  # print(dataframe %>% filter(country == "Brazil"), n = 20)
  # print(dataframe %>% filter(country == "Bulgaria"), n = 20)
  # print(dataframe %>% filter(country == "Burundi"), n = 20)
  # print(dataframe %>% filter(country == "Cameroon"), n = 20)
  # print(dataframe %>% filter(country == "Canada"), n = 20)
  # print(dataframe %>% filter(country == "Chile"), n = 20)
  # print(dataframe %>% filter(country == "Colombia"), n = 20)
  # print(dataframe %>% filter(country == "Costa Rica"), n = 20)
  # print(dataframe %>% filter(country == "Croatia"), n = 20)
  # print(dataframe %>% filter(country == "Cuba"), n = 20)
  # print(dataframe %>% filter(country == "Cyprus"), n = 20)
  # print(dataframe %>% filter(country == "Czechia"), n = 20)
  # print(dataframe %>% filter(country == "Dominican Republic"), n = 20)
  # print(dataframe %>% filter(country == "Ecuador"), n = 20)
  # print(dataframe %>% filter(country == "El Salvador"), n = 20)
  # print(dataframe %>% filter(country == "Estonia"), n = 20)
  # print(dataframe %>% filter(country == "Eswatini"), n = 20)
  # print(dataframe %>% filter(country == "Ethiopia"), n = 20)
  # print(dataframe %>% filter(country == "Fiji"), n = 20)
  # print(dataframe %>% filter(country == "Finland"), n = 20)
  # print(dataframe %>% filter(country == "France"), n = 20)
  # print(dataframe %>% filter(country == "Georgia"), n = 20)
  # print(dataframe %>% filter(country == "Germany"), n = 20)
  # print(dataframe %>% filter(country == "Ghana"), n = 20)
  # print(dataframe %>% filter(country == "Greece"), n = 20)
  # print(dataframe %>% filter(country == "Guatemala"), n = 20)
  # print(dataframe %>% filter(country == "Guyana"), n = 20)
  # print(dataframe %>% filter(country == "Honduras"), n = 20)
  # print(dataframe %>% filter(country == "Hungary"), n = 20)
  # print(dataframe %>% filter(country == "Iceland"), n = 20)
  # print(dataframe %>% filter(country == "India"), n = 20)
  # print(dataframe %>% filter(country == "Indonesia"), n = 20)
  # print(dataframe %>% filter(country == "Iran"), n = 20)
  # print(dataframe %>% filter(country == "Ireland"), n = 20)
  # print(dataframe %>% filter(country == "Israel"), n = 20)
  # print(dataframe %>% filter(country == "Italy"), n = 20)
  # print(dataframe %>% filter(country == "Jamaica"), n = 20)
  # print(dataframe %>% filter(country == "Japan"), n = 20)
  # print(dataframe %>% filter(country == "Jordan"), n = 20)
  # print(dataframe %>% filter(country == "Kazakhstan"), n = 20)
  
  
  
  
  
  
  ###............................................................................
  # The last 1000 or so rows
  
  # Standardize Leader Names for Kazakhstan (already done)
  dataframe$speaker[dataframe$country == "Kazakhstan" & dataframe$speaker %in% c("Nazarbayev", "Nursultan Nazarbayev I")] <- "Nursultan Nazarbayev"
  #Smailov becomes Smaiylov
  dataframe$speaker[dataframe$country == "Kazakhstan" & dataframe$speaker == "Smailov"] <- "Smaiylov" #LAST NAME ONLY
  dataframe$speaker[dataframe$country == "Kazakhstan" & dataframe$speaker == "Smaiylov"] <- "Alikhan Smaiylov"
  
  # Standardize Leader Names for Kenya
  #dataframe$speaker[dataframe$country == "Kenya" & dataframe$speaker == "Kenyatta"] <- "Uhuru Kenyatta"
  dataframe$speaker[dataframe$country == "Kenya" & dataframe$speaker == "Kenyatta"] <- "Uhuru Kenyatta"
  
  # Standardize Leader Names for Kuwait (already done)
  #dataframe$speaker[dataframe$country == "Kuwait" & dataframe$speaker == "Jabir As-Sabah"] <- "Jaber Al-Ahmad Al-Sabah"
  dataframe$speaker[dataframe$country == "Kuwait" & dataframe$speaker == "Jabir As-Sabah"] <- "Jaber Al-Sabah III"
  #
  dataframe$speaker[dataframe$country == "Kuwait" & dataframe$speaker == "Jabir Ahmad Al Sabah"] <- "Sheikh Sabah IV"
  dataframe$speaker[dataframe$country == "Kuwait" & dataframe$speaker == "Al-Sabah"] <- "Sheikh Sabah IV"
  dataframe$speaker[dataframe$country == "Kuwait" & dataframe$speaker == "Sheikh Sabah IV"] <- "Sabah Al-Ahmad Al-Jaber Al-Sabah"
  
  #Kyrgyzstan (Kurmanbek S. Bakiyev to Bakiyev)
  dataframe$speaker[dataframe$country == "Kyrgyzstan" & dataframe$speaker == "Kurmanbek S. Bakiyev"] <- "Bakiyev" #LAST NAME ONLY
  dataframe$speaker[dataframe$country == "Kyrgyzstan" & dataframe$speaker == "Bakiyev"] <- "Kurmanbek Bakiyev"
  dataframe$speaker[dataframe$country == "Kyrgyzstan" & dataframe$speaker == "Akayev"] <- "Askar Akayev"

  #Latvia - there are some duplicate variations in "Aigars Kalvitis, Einars Repse, Laimdota Straujuma, Maris Kucinskis, Valdis Dombrovskis, Karins, Levits, Kucinskis, Berzins, Skele, Krasts, Kristopans, Straujuma"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Kalvitis"] <- "Aigars Kalvitis"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Repse"] <- "Einars Repse"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Straujuma"] <- "Laimdota Straujuma"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Kucinskis"] <- "Maris Kucinskis"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Dombrovskis"] <- "Valdis Dombrovskis"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Karins"] <- "Krisjanis Karins"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Levits"] <- "Egils Levits"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Berzins"] <- "Andris Berzins"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Skele"] <- "Andris Skele"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Krasts"] <- "Guntars Krasts"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Kristopans"] <- "Vilis Kristopans"
  dataframe$speaker[dataframe$country == "Latvia" & dataframe$speaker == "Straujuma"] <- "Laimdota Straujuma"
  
  
  # Standardize Leader Names for Lebanon (it's okay because more specific)
  dataframe$speaker[dataframe$country == "Lebanon" & dataframe$speaker == "Suleiman"] <- "Michel Suleiman"
  #dataframe$speaker[dataframe$country == "Lebanon" & dataframe$speaker == "Mikati"] <- "Najib Mikati"
  dataframe$speaker[dataframe$country == "Lebanon" & dataframe$speaker == "Mikati"] <- "Najib Mikati"

  # Standardize Leader Names for Lithuania
  dataframe$speaker[dataframe$country == "Lithuania" & dataframe$speaker == "Adamkus"] <- "Valdas Adamkus"
  dataframe$speaker[dataframe$country == "Lithuania" & dataframe$speaker %in% c("Grybauskaite", "Dalia Grybauskaite")] <- "Dalia Grybauskaite"
  dataframe$speaker[dataframe$country == "Lithuania" & dataframe$speaker == "Kubilius"] <- "Andrius Kubilius"
  dataframe$speaker[dataframe$country == "Lithuania" & dataframe$speaker == "Brazauskas"] <- "Algirdas Brazauskas"
  #dataframe$speaker[dataframe$country == "Lithuania" & dataframe$speaker == "Šimonytė"] <- "Ingrida Šimonytė"
  dataframe$speaker[dataframe$country == "Lithuania" & dataframe$speaker %in% c("Šimonytė", "Simonyte")] <- "Ingrida Simonyte"
  dataframe$speaker[dataframe$country == "Lithuania" & dataframe$speaker == "Nauseda"] <- "Gitanas Nauseda"
  
  
  
  # Standardize Leader Names for Malaysia
  #dataframe$speaker[dataframe$country == "Malaysia" & dataframe$speaker == "Najib Tun Razak"] <- "Najib Razak"
  # Malaysia
  dataframe$speaker[dataframe$country == "Malaysia" & dataframe$speaker == "Ahmad Badawi"] <- "Abdullah Ahmad Badawi"
  dataframe$speaker[dataframe$country == "Malaysia" & dataframe$speaker == "Mahathir Bin Mohamed"] <- "Mahathir Mohamad"
  dataframe$speaker[dataframe$country == "Malaysia" & dataframe$speaker == "Muhyiddin Yassin"] <- "Muhyiddin Yassin"
  
  
  # Standardize Leader Names for Mexico 
  dataframe$speaker[dataframe$country == "Mexico" & dataframe$speaker %in% c("Andres Manuel Lopez Obrador", "Obrador", "Lopez Obrador")] <- "Obrador" #LAST NAME ONLY
  dataframe$speaker[dataframe$country == "Mexico" & dataframe$speaker == "Obrador"] <- "Andres Manuel Lopez Obrador"
  dataframe$speaker[dataframe$country == "Mexico" & dataframe$speaker %in% c("Fox", "Vicente Fox Quesada")] <- "Vicente Fox"
  dataframe$speaker[dataframe$country == "Mexico" & dataframe$speaker == "Calderon"] <- "Felipe Calderon"
  
  
  # Standardize Leader Names for Malta
  dataframe$speaker[dataframe$country == "Malta" & dataframe$speaker == "Marie Louise Coleiro Preca"] <- "Marie-Louise Coleiro Preca"
  dataframe$speaker[dataframe$country == "Malta" & dataframe$speaker == "Adami"] <- "Eddie Fenech Adami"
  dataframe$speaker[dataframe$country == "Malta" & dataframe$speaker == "Gonzi"] <- "Lawrence Gonzi"
  dataframe$speaker[dataframe$country == "Malta" & dataframe$speaker == "Muscat"] <- "Joseph Muscat"
  dataframe$speaker[dataframe$country == "Malta" & dataframe$speaker == "Abela"] <- "Robert Abela"

  # Standardize Leader Names for Moldova
  dataframe$speaker[dataframe$country == "Moldova" & dataframe$speaker == "Voronin"] <- "Vladimir Voronin"
  dataframe$speaker[dataframe$country == "Moldova" & dataframe$speaker == "Timofti"] <- "Nicolae Timofti"
  dataframe$speaker[dataframe$country == "Moldova" & dataframe$speaker == "Voronin"] <- "Vladimir Voronin"
  dataframe$speaker[dataframe$country == "Moldova" & dataframe$speaker == "Lupu"] <- "Marian Lupu"
  dataframe$speaker[dataframe$country == "Moldova" & dataframe$speaker == "Gavrilita"] <- "Natalia Gavrilita"
  
  #Mongolia
  dataframe$speaker[dataframe$country == "Mongolia" & dataframe$speaker == "Enkhbayar"] <- "Nambaryn Enkhbayar"
  
  
  # Standardize Leader Names for Montenegro (already done)
  dataframe$speaker[dataframe$country == "Montenegro" & dataframe$speaker %in% c("Djukanovic", "Dukanovic")] <- "Milo Djukanovic"
  
  # Standardize Leader Names for Morocco
  dataframe$speaker[dataframe$country == "Morocco" & dataframe$speaker %in% c("King Mohammed VI", "Muhammad VI")] <- "Mohammed VI"
  dataframe$speaker[dataframe$country == "Morocco" & dataframe$speaker == "Akhannouch"] <- "Aziz Akhannouch"

  # Netherlands
  dataframe$speaker[dataframe$country == "Netherlands" & dataframe$speaker %in% c("Rutte", "M. Rutte")] <- "Mark Rutte"
  dataframe$speaker[dataframe$country == "Netherlands" & dataframe$speaker == "Willem-Alexander"] <- "King Willem-Alexander"

  #North Macedonia - Gruevski  should be Nikola Gruevski
  dataframe$speaker[dataframe$country == "North Macedonia" & dataframe$speaker == "Gruevski"] <- "Nikola Gruevski"
  #dataframe$speaker[dataframe$country == "North Macedonia" & dataframe$speaker == "Kovačevski"] <- "Dimitar Kovačevski"
  dataframe$speaker[dataframe$country == "North Macedonia" & dataframe$speaker == "Kovačevski"] <- "Dimitar Kovacevski"
  dataframe$speaker[dataframe$country == "North Macedonia" & dataframe$speaker == "Dimitriev"] <- "Emil Dimitriev"
  dataframe$speaker[dataframe$country == "North Macedonia" & dataframe$speaker %in% c("Spasovksi", "Spasovski")] <- "Oliver Spasovski"
  dataframe$speaker[dataframe$country == "North Macedonia" & dataframe$speaker == "Zaev"] <- "Zoran Zaev"

  # Standardize Leader Names for Norway 
  dataframe$speaker[dataframe$country == "Norway" & dataframe$speaker == "Solberg"] <- "Erna Solberg"
  dataframe$speaker[dataframe$country == "Norway" & dataframe$speaker == "Bondevik"] <- "Kjell Magne Bondevik"
  dataframe$speaker[dataframe$country == "Norway" & dataframe$speaker == "Stoltenberg"] <- "Jens Stoltenberg"
  dataframe$speaker[dataframe$country == "Norway" & dataframe$speaker == "Støre"] <- "Jonas Gahr Støre"
  
  # Panama
  dataframe$speaker[dataframe$country == "Panama" & dataframe$speaker == "Martinelli"] <- "Ricardo Martinelli"
  
  # Paraguay
  dataframe$speaker[dataframe$country == "Paraguay" & dataframe$speaker %in% c("Duarte", "Nicanor Duarte Frutos")] <- "Nicanor Duarte"
  
  # Peru
  dataframe$speaker[dataframe$country == "Peru" & dataframe$speaker %in% c("Garcia", "Garcia Perez")] <- "Alan Garcia"
  
  # Standardize Leader Names for Peru (already done)
  #dataframe$speaker[dataframe$country == "Peru" & dataframe$speaker == "Ollanta Humala"] <- "Ollanta Humala Tasso"
  
  # Standardize Leader Names for Philippines (already done)
  #dataframe$speaker[dataframe$country == "Philippines" & dataframe$speaker == "Gloria Macapagal Arroyo"] <- "Gloria Arroyo"
  #dataframe$speaker[dataframe$country == "Philippines" & dataframe$speaker == "Benigno Aquino III"] <- "Noynoy Aquino"
  dataframe$speaker[dataframe$country == "Philippines" & dataframe$speaker == "Estrada"] <- "Joseph Estrada"
  dataframe$speaker[dataframe$country == "Philippines" & dataframe$speaker == "Gloria Macapagal-Arroyo"] <- "Gloria Macapagal Arroyo"
  
  
  # Standardize Leader Names for Poland (with correct handling of the Kaczynski cases)
  #Tusk to Donald TUsk
  dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker == "Tusk"] <- "Donald Tusk"
  dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker %in% c("Beate Szydlo", "Beata Szydło")] <- "Beata Szydlo"
  dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker %in% c("Morawiecki", "Mateusz Morawiecki")] <- "Mateusz Morawiecki"
  dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker %in% c("Duda", "Andrzej Duda")] <- "Andrzej Duda"
  dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker == "Kopacz"] <- "Ewa Kopacz"
  dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker == "Komorowski"] <- "Bronislaw Komorowski"
  dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker == "Kwasniewski"] <- "Aleksander Kwasniewski"
  #Miller becomes Leszek Miller
  dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker == "Miller"] <- "Leszek Miller"
  
  # Correct handling for Kaczynski
  #dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker == "Kaczynski" & dataframe$year <= 2010] <- "Lech Kaczyński"
  dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker == "Kaczynski" & dataframe$year > 2010] <- "Jaroslaw Kaczynski"
  dataframe$speaker[dataframe$country == "Poland" & dataframe$speaker == "Kaczynski"] <- "Jaroslaw Kaczynski"
  
  
  # Standardize Leader Names for Romania
  # A. Nastase is Adrian Nastase
  dataframe$speaker[dataframe$country == "Romania" & dataframe$speaker == "A. Nastase"] <- "Adrian Nastase"
  #simplify Viorica Dăncilă to Viorica Dancila
  dataframe$speaker[dataframe$country == "Romania" & dataframe$speaker %in% c("Viorica Dăncilă","Dăncilă")] <- "Viorica Dancila"
  #and Dacian Cioloș  to Dacian Ciolos
  dataframe$speaker[dataframe$country == "Romania" & dataframe$speaker %in% c("Dacian Cioloș", "Cioloș")] <- "Dacian Ciolos"
  dataframe$speaker[dataframe$country == "Romania" & dataframe$speaker == "Ciucă"] <- "Nicolae Ciucă"
  dataframe$speaker[dataframe$country == "Romania" & dataframe$speaker == "Iohannis"] <- "Klaus Werner Iohannis"
  dataframe$speaker[dataframe$country == "Romania" & dataframe$speaker %in% c("Victor Ponta", "Ponta")] <- "Viktor Ponta"
  #Popescu-Tariceanu to Calin Popescu-Tariceanu
  dataframe$speaker[dataframe$country == "Romania" & dataframe$speaker == "Popescu-Tariceanu"] <- "Calin Popescu-Tariceanu"
  dataframe$speaker[dataframe$country == "Romania" & dataframe$speaker == "Grindeanu"] <- "Sorin Grindeanu"
  dataframe$speaker[dataframe$country == "Romania" & dataframe$speaker == "Tudose"] <- "Mihai Tudose"

  # Standardize Leader Names for Russia 
  dataframe$speaker[dataframe$country == "Russia" & dataframe$speaker %in% c("Dmitri Manu", "Dimitri Medvedev", "Medvedev")] <- "Dmitry Medvedev"
  #Putin to Vladimir Putin
  dataframe$speaker[dataframe$country == "Russia" & dataframe$speaker == "Putin"] <- "Vladimir Putin"
  
  #Saudia Arabia Abdullah and Salman
  dataframe$speaker[dataframe$country == "Saudi Arabia" & dataframe$speaker == "Abdullah"] <- "King Abdullah"
  dataframe$speaker[dataframe$country == "Saudi Arabia" & dataframe$speaker == "Salman"] <- "King Salman"
  
  # Standardize Leader Names for Serbia 
  dataframe$speaker[dataframe$country == "Serbia" & dataframe$speaker == "Vucic"] <- "Aleksandar Vucic"
  #and Aleksandar Vučić to Aleksandar Vucic
  dataframe$speaker[dataframe$country == "Serbia" & dataframe$speaker == "Aleksandar Vučić"] <- "Aleksandar Vucic"
  dataframe$speaker[dataframe$country == "Serbia" & dataframe$speaker %in% c("Dindic","Djindjic")] <- "Zoran Dindic"
  dataframe$speaker[dataframe$country == "Serbia" & dataframe$speaker == "Tadic"] <- "Boris Tadic"
  dataframe$speaker[dataframe$country == "Serbia" & dataframe$speaker == "Kostunica"] <- "Vojislav Kostunica"
  #dataframe$speaker[dataframe$country == "Serbia" & dataframe$speaker == "Dacic"] <- "Ivica Dačić"
  dataframe$speaker[dataframe$country == "Serbia" & dataframe$speaker == "Milosevic"] <- "Slobodan Milosevic"
  dataframe$speaker[dataframe$country == "Serbia" & dataframe$speaker == "Cvetkovic"] <- "Mirko Cvetkovic"
  dataframe$speaker[dataframe$country == "Serbia" & dataframe$speaker == "Dacic"] <- "Ivica Dacic"

  # Standardize Leader Names for Seychelles
  #dataframe$speaker[dataframe$country == "Seychelles" & dataframe$speaker == "Michel"] <- "James Michel"
  dataframe$speaker[dataframe$country == "Seychelles" & dataframe$speaker == "Michel"] <- "James Michel"

  # Standardize Leader Names for Singapore
  dataframe$speaker[dataframe$country == "Singapore" & dataframe$speaker == "Tony Tan"] <- "Tony Tan Keng Yam"
  dataframe$speaker[dataframe$country == "Singapore" & dataframe$speaker == "S R Nathan"] <- "S. R. Nathan"

  #Slovakia
  #Dzurinda to Mikulas Dzurinda
  dataframe$speaker[dataframe$country == "Slovakia" & dataframe$speaker == "Dzurinda"] <- "Mikulas Dzurinda"
  #Fico to Robert Fico
  dataframe$speaker[dataframe$country == "Slovakia" & dataframe$speaker == "Fico"] <- "Robert Fico"
  dataframe$speaker[dataframe$country == "Slovakia" & dataframe$speaker == "Meciar"] <- "Vladimir Meciar"
  dataframe$speaker[dataframe$country == "Slovakia" & dataframe$speaker == "Radicova"] <- "Iveta Radicova"
  dataframe$speaker[dataframe$country == "Slovakia" & dataframe$speaker == "Pellegrini"] <- "Peter Pellegrini"

  # Standardize Leader Names for Somalia
  #dataframe$speaker[dataframe$country == "Somalia" & dataframe$speaker == "Farmajo"] <- "Mohamed Abdullahi Farmajo"
  
  # Standardize Leader Names for South Africa 
  dataframe$speaker[dataframe$country == "South Africa" & dataframe$speaker %in% c("Mandela", "Nelson Mandela")] <- "Nelson Mandela"
  #and Mbeki to Thabo Mbeki
  dataframe$speaker[dataframe$country == "South Africa" & dataframe$speaker == "Mbeki"] <- "Thabo Mbeki"
  #and Zuma to Jacob Zuma
  dataframe$speaker[dataframe$country == "South Africa" & dataframe$speaker == "Zuma"] <- "Jacob Zuma"
  #and Ramaphosa to Cyril Ramaphosa
  dataframe$speaker[dataframe$country == "South Africa" & dataframe$speaker == "Ramaphosa"] <- "Cyril Ramaphosa"
  dataframe$speaker[dataframe$country == "South Africa" & dataframe$speaker == "Motlanthe"] <- "Kgalema Motlanthe"
  
  # Standardize Leader Names for Spain
  dataframe$speaker[dataframe$country == "Spain" & dataframe$speaker %in% c("Jose Luis Rodriguez Zapatero", "Jose Zapatero", "Zapatero", "Rodriguez Zapatero")] <- "Jose Zapatero"
  dataframe$speaker[dataframe$country == "Spain" & dataframe$speaker %in% c("Rajoy Brey", "Mariano Rajoy Brey", "Mariano Rajoy")] <- "Mariano Rajoy"
  #sanchez to Pedro Sanchez
  dataframe$speaker[dataframe$country == "Spain" & dataframe$speaker == "Sanchez"] <- "Pedro Sanchez"
  dataframe$speaker[dataframe$country == "Spain" & dataframe$speaker == "Aznar"] <- "Jose Maria Aznar"
  dataframe$speaker[dataframe$country == "Spain" & dataframe$speaker == "Perez-Castejon"] <- "Pedro Sanchez"

  # Standardize Leader Names for Sri Lanka (already done)
  dataframe$speaker[dataframe$country == "Sri Lanka" & dataframe$speaker == "Sirisena"] <- "Maithripala Sirisena"
  dataframe$speaker[dataframe$country == "Sri Lanka" & dataframe$speaker %in% c("M. Rajapakse", "M. Rajapaksa")] <- "Mahinda Rajapaksa"
  dataframe$speaker[dataframe$country == "Sri Lanka" & dataframe$speaker == "Kumaratunga"] <- "Chandrika Kumaratunga"
  
  # Standardize Leader Names for Sudan (already matches so don't do)
  #dataframe$speaker[dataframe$country == "Sudan" & dataframe$speaker == "Abdelrahman Burhan"] <- "Abdel Fattah al-Burhan"
  
  # Standardize Leader Names for Sweden
  dataframe$speaker[dataframe$country == "Sweden" & dataframe$speaker %in% c("Lofven", "Löfven")] <- "Stefan Löfven"
  #"Stefan Löfven" to "Stefan Lofven"
  dataframe$speaker[dataframe$country == "Sweden" & dataframe$speaker == "Stefan Löfven"] <- "Stefan Lofven"
  #dataframe$speaker[dataframe$country == "Sweden" & dataframe$speaker == "Goran Persson"] <- "Göran Persson"
  dataframe$speaker[dataframe$country == "Sweden" & dataframe$speaker == "Andersson"] <- "Magdalena Andersson"
  dataframe$speaker[dataframe$country == "Sweden" & dataframe$speaker == "Persson"] <- "Goran Persson"
  dataframe$speaker[dataframe$country == "Sweden" & dataframe$speaker == "Reinfeldt"] <- "Fredrik Reinfeldt"
  dataframe$speaker[dataframe$country == "Sweden" & dataframe$speaker == "Kristersson"] <- "Ulf Kristersson"
  
  
  # Standardize Leader Names for Switzerland (already done)
  dataframe$speaker[dataframe$country == "Switzerland" & dataframe$speaker %in% c("Alan Berset", "Berset", "Alain Berset") ] <- "Alan Berset/Christian Levrat"
  dataframe$speaker[dataframe$country == "Switzerland" & dataframe$speaker %in% c("Guy Parmelin", "Parmelin" ) ] <- "Guy Parmelin/Christoph Blocher"
  dataframe$speaker[dataframe$country == "Switzerland" & dataframe$speaker %in% c("Doris Leuthard", "Leuthard", "Doris") ] <- "Doris Leuthard/Christophe Darbellay"
  dataframe$speaker[dataframe$country == "Switzerland" & dataframe$speaker == "Schneider-Ammann"] <- "Johann Schneider-Ammann"
  dataframe$speaker[dataframe$country == "Switzerland" & dataframe$speaker == "Sommaruga"] <- "Simonetta Sommaruga"

  # Standardize Leader Names for Taiwan (already done)
  # Consistent for records present
  
  # Standardize Leader Names for Tajikistan
  dataframe$speaker[dataframe$country == "Tajikistan" & dataframe$speaker == "Rahmon"] <- "Emomali Rahmon"
  dataframe$speaker[dataframe$country == "Tajikistan" & dataframe$speaker == "Rakhmonov"] <- "Emomali Rahmon"
  
  # Standardize Leader Names for Tanzania
  #dataframe$speaker[dataframe$country == "Tanzania" & dataframe$speaker == "Kikwete"] <- "Jakaya Kikwete"
  dataframe$speaker[dataframe$country == "Tanzania" & dataframe$speaker %in% c("Mizengo P. Pinda", "Mizengo Peter Pinda")] <- "Mizengo Pinda"
  dataframe$speaker[dataframe$country == "Tanzania" & dataframe$speaker == "Kikwete"] <- "Jakaya Kikwete"
  dataframe$speaker[dataframe$country == "Tanzania" & dataframe$speaker == "Magufuli"] <- "John Magufuli"
  
  # Standardize Leader Names for Thailand 
  dataframe$speaker[dataframe$country == "Thailand" & dataframe$speaker == "Prayut Chan-o-cha"] <- "Prayuth Chan-ocha"
  #dataframe$speaker[dataframe$country == "Thailand" & dataframe$speaker == "Prayuth Chan-ocha"] <- "Prayut Chan-o-cha"
  
  dataframe$speaker[dataframe$country == "Thailand" & dataframe$speaker == "Shinawatra"] <- "Thaksin Shinawatra"
  dataframe$speaker[dataframe$country == "Thailand" & dataframe$speaker %in% c("Chan-o-cha", "Prayuth Chan-o-cha") ] <- "Prayuth Chan-ocha"
  dataframe$speaker[dataframe$country == "Thailand" & dataframe$speaker == "Leekpai"] <- "Chuan Leekpai"
  dataframe$speaker[dataframe$country == "Thailand" & dataframe$speaker == "Chulanont"] <- "Surayud Chulanont"
  dataframe$speaker[dataframe$country == "Thailand" & dataframe$speaker == "Vejjajiva"] <- "Abhisit Vejjajiva"
  dataframe$speaker[dataframe$country == "Thailand" & dataframe$speaker == "Yingluck"] <- "Yingluck Shinawatra"

  # Standardize Leader Names for Timor-Leste (consistency checks, no changes needed)
  # replace Ruak with Matan Ruak
  dataframe$speaker[dataframe$country == "Timor-Leste" & dataframe$speaker %in% c("Ruak", "Matan Ruak")] <- "Taur Matan Ruak"
  
  # Standardize Leader Names for Trinidad and Tobago (already done)
  #dataframe$speaker[dataframe$country == "Trinidad and Tobago" & dataframe$speaker == "Persad-Bissessar"] <- "Kamla Persad-Bissessar"
  dataframe$speaker[dataframe$country == "Trinidad and Tobago" & dataframe$speaker == "Kamla Persad-Bissessar"] <- "Persad-Bissessar"
  dataframe$speaker[dataframe$country == "Trinidad and Tobago" & dataframe$speaker == "Persad-Bissessar"] <- "Kamla Persad-Bissessar"
  dataframe$speaker[dataframe$country == "Trinidad and Tobago" & dataframe$speaker == "Rowley"] <- "Keith Rowley"

  # Standardize Leader Names for Turkey (already done)
  dataframe$speaker[dataframe$country == "Turkey" & dataframe$speaker %in% c("Recep T. Erdogan", "Recep Tayyip Erdoğan", "Recep Tayyip Erdogan")] <- "Erdoğan" #LAST NAME ONLY
  dataframe$speaker[dataframe$country == "Turkey" & dataframe$speaker == "Erdoğan"] <- "Recep Tayyip Erdogan"
  dataframe$speaker[dataframe$country == "Turkey" & dataframe$speaker == "Erdogan"] <- "Recep Tayyip Erdogan"
  dataframe$speaker[dataframe$country == "Turkey" & dataframe$speaker == "Abdullah Gul"] <- "Abdullah Gül"
  
  # Turkmenistan
  dataframe$speaker[dataframe$country == "Turkmenistan" & dataframe$speaker == "Niyazov"] <- "Saparmurat Niyazov"
  dataframe$speaker[dataframe$country == "Turkmenistan" & dataframe$speaker %in% c("Berdimuhamedow","Berdymukhammedov")] <- "Gurbanguly Berdimuhamedow"
  
  # Standardize Leader Names for UAE
  dataframe$speaker[dataframe$country == "UAE" & dataframe$speaker %in% c("M.b.R. Al Maktoum", "Mohammed b.R. Al Maktoum", "Maktoum")] <- "Mohammed bin Rashid Al Maktoum"
  dataframe$speaker[dataframe$country == "UAE" & dataframe$speaker == "An-Nahayan" & dataframe$year == 2002] <- "Mohammed bin Rashid Al Maktoum"
  dataframe$speaker[dataframe$country == "UAE" & dataframe$speaker == "Khalifa Al Nahayan"] <- "Mohammed bin Rashid Al Maktoum"
  
  # Standardize Leader Names for Uganda 
  dataframe$speaker[dataframe$country == "Uganda" & dataframe$speaker %in% c("Museveni", "Yoweri Museveni")] <- "Yoweri Museveni"
  
  # Standardize Leader Names for Ukraine 
  dataframe$speaker[dataframe$country == "Ukraine" & dataframe$speaker == "Poroshenko"] <- "Petro Poroshenko"
  dataframe$speaker[dataframe$country == "Ukraine" & dataframe$speaker == "Yanukovych"] <- "Viktor Yanukovych"
  #Tymoshenko to Yulia Tymoshenko
  dataframe$speaker[dataframe$country == "Ukraine" & dataframe$speaker == "Tymoshenko"] <- "Yulia Tymoshenko"
  dataframe$speaker[dataframe$country == "Ukraine" & dataframe$speaker == "Zelensky"] <- "Volodymyr Zelensky"

  # Standardize Leader Names for United Kingdom (already done)
  dataframe$speaker[dataframe$country == "United Kingdom" & dataframe$speaker == "Cameron"] <- "David Cameron"
  dataframe$speaker[dataframe$country == "United Kingdom" & dataframe$speaker == "May"] <- "Theresa May"
  dataframe$speaker[dataframe$country == "United Kingdom" & dataframe$speaker == "Johnson"] <- "Boris Johnson"
  dataframe$speaker[dataframe$country == "United Kingdom" & dataframe$speaker == "Sunak"] <- "Rishi Sunak"
  dataframe$speaker[dataframe$country == "United Kingdom" & dataframe$speaker == "Johnson"] <- "Boris Johnson"
  dataframe$speaker[dataframe$country == "United Kingdom" & dataframe$speaker == "Brown"] <- "Gordon Brown"
  dataframe$speaker[dataframe$country == "United Kingdom" & dataframe$speaker == "Blair"] <- "Tony Blair"
  
  # Standardize Leader Names for United States
  dataframe$speaker[dataframe$country == "United States of America" & dataframe$speaker %in% c("George W. Bush", "G.W. Bush") ] <- "W. Bush" #LAST NAME ONLY
  dataframe$speaker[dataframe$country == "United States of America" & dataframe$speaker == "W. Bush"] <- "George W. Bush"
  dataframe$speaker[dataframe$country == "United States of America" & dataframe$speaker %in% c("Barack Obama", "B. Obama") ] <- "Obama" #LAST NAME ONLY
  dataframe$speaker[dataframe$country == "United States of America" & dataframe$speaker == "Obama"] <- "Barack Obama"
  dataframe$speaker[dataframe$country == "United States of America" & dataframe$speaker %in% c("Donald Trump", "D. Trump") ] <- "Trump" #LAST NAME ONLY
  dataframe$speaker[dataframe$country == "United States of America" & dataframe$speaker == "Trump"] <- "Donald Trump"
  dataframe$speaker[dataframe$country == "United States of America" & dataframe$speaker %in% c("Joe Biden", "J. Biden") ] <- "Biden" #LAST NAME ONLY
  dataframe$speaker[dataframe$country == "United States of America" & dataframe$speaker == "Biden"] <- "Joe Biden"

  #Uzbekistan
  #Karimov to Islam Karimov
  dataframe$speaker[dataframe$country == "Uzbekistan" & dataframe$speaker == "Karimov"] <- "Islam Karimov"
  # Example of recoding specific case with full name variants
  #dataframe$speaker[dataframe$speaker == "Islam Karimov" | dataframe$speaker == "Karimov"] <- "Islam Karimov"
  
  # Standardize Leader Names for Venezuela 
  dataframe$speaker[dataframe$country == "Venezuela" & dataframe$speaker %in% c("Nicolas Maduro", "Nicolas Maduro Moros")] <- "Nicolas Maduro"
  
  
  
  # Standardize Leader Names for Vietnam
  #dataframe$speaker[dataframe$country == "Vietnam" & dataframe$speaker == "Phu Trong"] <- "Nguyen Phu Trong"
  dataframe$speaker[dataframe$country == "Vietnam" & dataframe$speaker == "Chinh"] <- "Pham Minh Chinh"

  # Standardize Leader Names for Zimbabwe
  #dataframe$speaker[dataframe$country == "Zimbabwe" & dataframe$speaker == "Mnangagwa"] <- "Emmerson Mnangagwa"
  dataframe$speaker[dataframe$country == "Zimbabwe" & dataframe$speaker == "Mugabe"] <- "Robert Mugabe"
  dataframe$speaker[dataframe$country == "Zimbabwe" & dataframe$speaker == "Mnangagwa"] <- "Emmerson Mnangagwa"

  #.......................................................................
  # New country blocks (leaders from tenure file not previously in fixNames)

  # Standardize Leader Names for Laos
  dataframe$speaker[dataframe$country == "Laos" & dataframe$speaker %in% c("Phounsavanh", "Phoumsavanh")] <- "Nouhak Phoumsavanh"
  dataframe$speaker[dataframe$country == "Laos" & dataframe$speaker == "Siphandon"] <- "Khamtai Siphandone"
  dataframe$speaker[dataframe$country == "Laos" & dataframe$speaker == "Sayasone"] <- "Choummaly Sayasone"
  dataframe$speaker[dataframe$country == "Laos" & dataframe$speaker == "Vorachit"] <- "Bounnhang Vorachit"
  dataframe$speaker[dataframe$country == "Laos" & dataframe$speaker == "Sisoulith"] <- "Thongloun Sisoulith"
  dataframe$speaker[dataframe$country == "Laos" & dataframe$speaker == "Viphavanh"] <- "Phankham Viphavanh"

  # Standardize Leader Names for Lesotho
  dataframe$speaker[dataframe$country == "Lesotho" & dataframe$speaker == "Mokhehle"] <- "Ntsu Mokhehle"
  dataframe$speaker[dataframe$country == "Lesotho" & dataframe$speaker == "Mosisili"] <- "Pakalitha Mosisili"
  dataframe$speaker[dataframe$country == "Lesotho" & dataframe$speaker == "Thabane"] <- "Tom Thabane"

  # Standardize Leader Names for Luxembourg
  dataframe$speaker[dataframe$country == "Luxembourg" & dataframe$speaker == "Bettel"] <- "Xavier Bettel"

  # Standardize Leader Names for Madagascar
  dataframe$speaker[dataframe$country == "Madagascar" & dataframe$speaker == "Rajoelina"] <- "Andry Rajoelina"

  # Standardize Leader Names for Maldives
  dataframe$speaker[dataframe$country == "Maldives" & dataframe$speaker == "Gayoom"] <- "Maumoon Abdul Gayoom"

  # Standardize Leader Names for Rwanda
  dataframe$speaker[dataframe$country == "Rwanda" & dataframe$speaker == "Makuza"] <- "Bernard Makuza"

  # Standardize Leader Names for Solomon Islands
  dataframe$speaker[dataframe$country == "Solomon Islands" & dataframe$speaker == "Sogavare"] <- "Manasseh Sogavare"

  # Standardize Leader Names for The Gambia
  dataframe$speaker[dataframe$country == "The Gambia" & dataframe$speaker == "Barrow"] <- "Adama Barrow"

  # Standardize Leader Names for Vanuatu
  dataframe$speaker[dataframe$country == "Vanuatu" & dataframe$speaker == "Salwai"] <- "Charlot Salwai"

  # # Print to verify all changes were effective
  # print(dataframe %>% filter(country == "Poland"), n = 20)
  # print(dataframe %>% filter(country == "Kazakhstan"), n = 20)
  # print(dataframe %>% filter(country == "Kenya"), n = 20)
  # print(dataframe %>% filter(country == "Kuwait"), n = 20)
  # print(dataframe %>% filter(country == "Lebanon"), n = 20)
  # print(dataframe %>% filter(country == "Lithuania"), n = 20)
  # print(dataframe %>% filter(country == "Malaysia"), n = 20)
  # print(dataframe %>% filter(country == "Mexico"), n = 20)
  # print(dataframe %>% filter(country == "Moldova"), n = 20)
  # print(dataframe %>% filter(country == "Montenegro"), n = 20)
  # print(dataframe %>% filter(country == "Morocco"), n = 20)
  # print(dataframe %>% filter(country == "Norway"), n = 20)
  # print(dataframe %>% filter(country == "Peru"), n = 20)
  # print(dataframe %>% filter(country == "Philippines"), n = 20)
  # print(dataframe %>% filter(country == "Romania"), n = 20)
  # print(dataframe %>% filter(country == "Russia"), n = 20)
  # print(dataframe %>% filter(country == "Serbia"), n = 20)
  # print(dataframe %>% filter(country == "Seychelles"), n = 20)
  # print(dataframe %>% filter(country == "Somalia"), n = 20)
  # print(dataframe %>% filter(country == "South Africa"), n = 20)
  # print(dataframe %>% filter(country == "Spain"), n = 20)
  # print(dataframe %>% filter(country == "Sri Lanka"), n = 20)
  # print(dataframe %>% filter(country == "Sudan"), n = 20)
  # print(dataframe %>% filter(country == "Sweden"), n = 20)
  # print(dataframe %>% filter(country == "Switzerland"), n = 20)
  # print(dataframe %>% filter(country == "Tajikistan"), n = 20)
  # print(dataframe %>% filter(country == "Tanzania"), n = 20)
  # print(dataframe %>% filter(country == "Thailand"), n = 20)
  # print(dataframe %>% filter(country == "Trinidad and Tobago"), n = 20)
  # print(dataframe %>% filter(country == "Turkey"), n = 20)
  # print(dataframe %>% filter(country == "UAE"), n = 20)
  # print(dataframe %>% filter(country == "Uganda"), n = 20)
  # print(dataframe %>% filter(country == "Ukraine"), n = 20)
  # print(dataframe %>% filter(country == "United Kingdom"), n = 20)
  # print(dataframe %>% filter(country == "United States of America"), n = 20)
  # print(dataframe %>% filter(country == "Venezuela"), n = 20)
  # print(dataframe %>% filter(country == "Vietnam"), n = 20)
  # print(dataframe %>% filter(country == "Zimbabwe"), n = 20)
  
  return(dataframe)
        

}


